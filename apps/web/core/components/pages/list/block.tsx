/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef } from "react";
import { observer } from "mobx-react";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { ChevronRightIcon, PageIcon } from "@plane/propel/icons";
// plane imports
import { cn, getPageName } from "@plane/utils";
// components
import { ListItem } from "@/components/core/list";
import { BlockItemAction } from "@/components/pages/list/block-item-action";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";
// plane web hooks
import type { EPageStoreType } from "@/plane-web/hooks/store";
import { usePage, usePageStore } from "@/plane-web/hooks/store";

type TPageListBlock = {
  pageId: string;
  storeType: EPageStoreType;
  spacingLeft?: number;
};

export const PageListBlock = observer(function PageListBlock(props: TPageListBlock) {
  const { pageId, storeType, spacingLeft = 0 } = props;
  // refs
  const parentRef = useRef(null);
  // hooks
  const page = usePage({
    pageId,
    storeType,
  });
  const { expandedPageIds, togglePageExpanded, getChildPageIds } = usePageStore(storeType);
  const { isMobile } = usePlatformOS();
  // handle page check
  if (!page) return null;
  // derived values
  const { name, logo_props, getRedirectionLink, sub_pages_count } = page;
  const isExpanded = expandedPageIds.has(pageId);
  const childPageIds = isExpanded ? getChildPageIds(pageId) : [];

  return (
    <div>
      <div style={spacingLeft > 0 ? { paddingLeft: `${spacingLeft}px` } : undefined}>
        <ListItem
          prependTitleElement={
            <div className="flex items-center gap-1">
              {sub_pages_count > 0 ? (
                <button
                  type="button"
                  className="flex h-5 w-5 flex-shrink-0 cursor-pointer items-center justify-center text-placeholder hover:text-tertiary"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    togglePageExpanded(pageId);
                  }}
                >
                  <ChevronRightIcon
                    className={cn("size-3.5 transition-transform", {
                      "rotate-90": isExpanded,
                    })}
                  />
                </button>
              ) : spacingLeft > 0 ? (
                <div className="w-5 flex-shrink-0" />
              ) : null}
              {logo_props?.in_use ? (
                <Logo logo={logo_props} size={16} type="lucide" />
              ) : (
                <PageIcon className="h-4 w-4 text-tertiary" />
              )}
            </div>
          }
          title={getPageName(name)}
          itemLink={getRedirectionLink()}
          actionableItems={<BlockItemAction page={page} parentRef={parentRef} storeType={storeType} />}
          isMobile={isMobile}
          parentRef={parentRef}
        />
      </div>
      {isExpanded &&
        childPageIds.map((childId) => (
          <PageListBlock key={childId} pageId={childId} storeType={storeType} spacingLeft={spacingLeft + 22} />
        ))}
    </div>
  );
});
