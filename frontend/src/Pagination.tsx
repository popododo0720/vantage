import { Fragment } from 'react'
import type { PageInfo } from './types'

const PAGE_SIZES = [10, 25, 50, 100] as const

function visiblePages(page: PageInfo): number[] {
  const pages = [...new Set([...page.navigable_pages, page.number])]
    .filter((item) => Number.isSafeInteger(item) && item > 0)
    .sort((left, right) => left - right)
  if (pages.length <= 7) return pages
  const keep = new Set([
    pages[0],
    pages[pages.length - 1],
    page.number - 2,
    page.number - 1,
    page.number,
    page.number + 1,
    page.number + 2,
  ])
  return pages.filter((item) => keep.has(item))
}

export function Pagination({
  page,
  pageSize,
  labels,
  onPage,
  onPageSize,
}: {
  page?: PageInfo
  pageSize: number
  labels: {
    rows: string
    page: string
    previousPage: string
    nextPage: string
  }
  onPage: (page: number) => void
  onPageSize: (size: (typeof PAGE_SIZES)[number]) => void
}) {
  if (!page) return null
  return (
    <div className="pagination">
      <span className="page-range">
        {page.item_from}-{page.item_to}
        {page.total_items !== null && <> / {page.total_items}</>}
      </span>
      <label className="page-size">
        <span>{labels.rows}</span>
        <select
          value={pageSize}
          onChange={(event) => onPageSize(Number(event.target.value) as (typeof PAGE_SIZES)[number])}
        >
          {PAGE_SIZES.map((size) => <option key={size}>{size}</option>)}
        </select>
      </label>
      <nav aria-label={labels.page}>
        <button
          type="button"
          className="page-button"
          aria-label={labels.previousPage}
          disabled={!page.has_previous}
          onClick={() => onPage(page.number - 1)}
        >
          {'<'}
        </button>
        {visiblePages(page).map((item, index, items) => (
          <Fragment key={item}>
            {index > 0 && item - items[index - 1] > 1 && <span className="page-gap">...</span>}
            <button
              type="button"
              className={item === page.number ? 'page-button current' : 'page-button'}
              aria-label={`${labels.page} ${item}`}
              aria-current={item === page.number ? 'page' : undefined}
              onClick={() => onPage(item)}
            >
              {item}
            </button>
          </Fragment>
        ))}
        <button
          type="button"
          className="page-button"
          aria-label={labels.nextPage}
          disabled={!page.has_next}
          onClick={() => onPage(page.number + 1)}
        >
          {'>'}
        </button>
      </nav>
    </div>
  )
}
