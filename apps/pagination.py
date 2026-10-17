from django.core.paginator import Paginator

DEFAULT_PAGE_SIZE = 20


def paginate(request, queryset, per_page=DEFAULT_PAGE_SIZE, page_number=None, page_param="page"):
    """Paginate ``queryset`` for the current request.

    Returns ``(page_obj, querystring)`` where ``querystring`` is the request's
    current GET parameters minus ``page_param`` so pagination links can preserve
    any active filters. ``page_obj`` carries ``elided_page_range`` and
    ``page_param`` ready for the shared pagination partial.

    ``page_number`` overrides the query-string page value when the caller needs a
    specific page (e.g. jumping to a highlighted row). ``page_param`` lets a page
    host more than one independent paginator (e.g. ``inst_page`` vs ``prof_page``).
    """
    paginator = Paginator(queryset, per_page)
    if page_number is None:
        page_number = request.GET.get(page_param)
    page_obj = paginator.get_page(page_number)
    page_obj.elided_page_range = list(
        paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)
    )
    page_obj.page_param = page_param
    params = request.GET.copy()
    params.pop(page_param, None)
    return page_obj, params.urlencode()
