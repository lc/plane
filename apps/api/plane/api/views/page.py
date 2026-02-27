# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiResponse, OpenApiRequest

# Module imports
from plane.api.serializers import PageSerializer, PageDetailSerializer
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import Page, ProjectPage
from .base import BaseAPIView
from plane.utils.openapi import (
    page_docs,
    PAGE_ID_PARAMETER,
    CURSOR_PARAMETER,
    PER_PAGE_PARAMETER,
    FIELDS_PARAMETER,
    EXPAND_PARAMETER,
    create_paginated_response,
    PAGE_CREATE_EXAMPLE,
    PAGE_UPDATE_EXAMPLE,
    PAGE_EXAMPLE,
    INVALID_REQUEST_RESPONSE,
    EXTERNAL_ID_EXISTS_RESPONSE,
    DELETED_RESPONSE,
)


class PageListCreateAPIEndpoint(BaseAPIView):
    """Page List and Create Endpoint"""

    serializer_class = PageSerializer
    model = Page
    permission_classes = [ProjectEntityPermission]
    use_read_replica = True

    def get_queryset(self):
        return (
            Page.objects.filter(workspace__slug=self.kwargs.get("slug"))
            .filter(
                projects__id=self.kwargs.get("project_id"),
                projects__project_projectmember__member=self.request.user,
                projects__project_projectmember__is_active=True,
            )
            .filter(parent__isnull=True)
            .filter(
                Q(owned_by=self.request.user) | Q(access=Page.PUBLIC_ACCESS)
            )
            .filter(archived_at__isnull=True)
            .select_related("workspace", "owned_by")
            .order_by("-created_at")
            .distinct()
        )

    @page_docs(
        operation_id="create_page",
        summary="Create page",
        description="Create a new page in a project.",
        request=OpenApiRequest(
            request=PageDetailSerializer,
            examples=[PAGE_CREATE_EXAMPLE],
        ),
        responses={
            201: OpenApiResponse(
                description="Page created",
                response=PageDetailSerializer,
                examples=[PAGE_EXAMPLE],
            ),
            400: INVALID_REQUEST_RESPONSE,
            409: EXTERNAL_ID_EXISTS_RESPONSE,
        },
    )
    def post(self, request, slug, project_id):
        """Create page

        Create a new page in a project.
        Supports external ID tracking for integration purposes.
        """
        serializer = PageDetailSerializer(
            data=request.data,
            context={
                "project_id": project_id,
                "owned_by_id": request.user.id,
                "description_html": request.data.get("description_html", "<p></p>"),
            },
        )
        if serializer.is_valid():
            if (
                request.data.get("external_id")
                and request.data.get("external_source")
                and Page.objects.filter(
                    workspace__slug=slug,
                    external_source=request.data.get("external_source"),
                    external_id=request.data.get("external_id"),
                ).exists()
            ):
                page = Page.objects.filter(
                    workspace__slug=slug,
                    external_id=request.data.get("external_id"),
                    external_source=request.data.get("external_source"),
                ).first()
                return Response(
                    {
                        "error": "Page with the same external id and external source already exists",
                        "id": str(page.id),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @page_docs(
        operation_id="list_pages",
        summary="List pages",
        description="Retrieve all pages for a project.",
        parameters=[
            CURSOR_PARAMETER,
            PER_PAGE_PARAMETER,
            FIELDS_PARAMETER,
            EXPAND_PARAMETER,
        ],
        responses={
            200: create_paginated_response(
                PageSerializer,
                "PaginatedPageResponse",
                "Paginated list of pages",
                "Paginated Pages",
            ),
        },
    )
    def get(self, request, slug, project_id):
        """List pages

        Retrieve all pages for a project.
        Returns paginated results when listing all pages.
        """
        return self.paginate(
            request=request,
            queryset=self.get_queryset(),
            on_results=lambda pages: PageSerializer(
                pages, many=True, fields=self.fields, expand=self.expand
            ).data,
        )


class PageDetailAPIEndpoint(BaseAPIView):
    """Page Detail Endpoint"""

    serializer_class = PageDetailSerializer
    model = Page
    permission_classes = [ProjectEntityPermission]
    use_read_replica = True

    def get_queryset(self):
        return (
            Page.objects.filter(workspace__slug=self.kwargs.get("slug"))
            .filter(
                projects__id=self.kwargs.get("project_id"),
                projects__project_projectmember__member=self.request.user,
                projects__project_projectmember__is_active=True,
            )
            .filter(
                Q(owned_by=self.request.user) | Q(access=Page.PUBLIC_ACCESS)
            )
            .select_related("workspace", "owned_by")
            .distinct()
        )

    @page_docs(
        operation_id="retrieve_page",
        summary="Retrieve page",
        description="Retrieve details of a specific page including its content.",
        parameters=[
            PAGE_ID_PARAMETER,
        ],
        responses={
            200: OpenApiResponse(
                description="Page retrieved",
                response=PageDetailSerializer,
                examples=[PAGE_EXAMPLE],
            ),
        },
    )
    def get(self, request, slug, project_id, page_id):
        """Retrieve page

        Retrieve details of a specific page including its content.
        """
        page = self.get_queryset().get(pk=page_id)
        serializer = PageDetailSerializer(
            page, fields=self.fields, expand=self.expand
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @page_docs(
        operation_id="update_page",
        summary="Update page",
        description="Partially update an existing page's properties like name, content, or access level.",
        parameters=[
            PAGE_ID_PARAMETER,
        ],
        request=OpenApiRequest(
            request=PageDetailSerializer,
            examples=[PAGE_UPDATE_EXAMPLE],
        ),
        responses={
            200: OpenApiResponse(
                description="Page updated",
                response=PageDetailSerializer,
                examples=[PAGE_EXAMPLE],
            ),
            400: INVALID_REQUEST_RESPONSE,
            409: EXTERNAL_ID_EXISTS_RESPONSE,
        },
    )
    def patch(self, request, slug, project_id, page_id):
        """Update page

        Partially update an existing page's properties like name, content, or access level.
        Locked pages cannot be updated. Only the page owner can change access level.
        """
        page = Page.objects.get(
            workspace__slug=slug, pk=page_id
        )

        # Check if page is in the project
        if not ProjectPage.objects.filter(
            project_id=project_id, page_id=page_id
        ).exists():
            return Response(
                {"error": "Page not found in this project"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if page.is_locked:
            return Response(
                {"error": "Page is locked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only owner can change access
        if (
            "access" in request.data
            and page.owned_by_id != request.user.id
        ):
            return Response(
                {"error": "Only the page owner can change access"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            request.data.get("external_id")
            and (page.external_id != str(request.data.get("external_id")))
            and Page.objects.filter(
                workspace__slug=slug,
                external_source=request.data.get(
                    "external_source", page.external_source
                ),
                external_id=request.data.get("external_id"),
            ).exists()
        ):
            return Response(
                {
                    "error": "Page with the same external id and external source already exists",
                    "id": str(page.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = PageDetailSerializer(page, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @page_docs(
        operation_id="delete_page",
        summary="Delete page",
        description="Permanently remove a page. Only the page owner can delete, and the page must be archived first.",
        parameters=[
            PAGE_ID_PARAMETER,
        ],
        responses={
            204: DELETED_RESPONSE,
        },
    )
    def delete(self, request, slug, project_id, page_id):
        """Delete page

        Permanently remove a page. Only the page owner can delete,
        and the page must be archived first.
        """
        page = Page.objects.get(
            workspace__slug=slug, pk=page_id
        )

        if not ProjectPage.objects.filter(
            project_id=project_id, page_id=page_id
        ).exists():
            return Response(
                {"error": "Page not found in this project"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only owner can delete
        if page.owned_by_id != request.user.id:
            return Response(
                {"error": "Only the page owner can delete the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if page.archived_at is None:
            return Response(
                {"error": "Page must be archived before deleting"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Detach children
        Page.objects.filter(parent=page).update(parent=None)
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
