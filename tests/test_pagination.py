"""Tests for the shared pagination helper (Phase 3)."""

from django.test import RequestFactory, SimpleTestCase

from apps.pagination import DEFAULT_PAGE_SIZE, paginate


class PaginateTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.items = list(range(100))

    def test_default_page_size(self):
        request = self.factory.get("/")
        page_obj, _ = paginate(request, self.items)
        self.assertEqual(len(page_obj.object_list), DEFAULT_PAGE_SIZE)
        self.assertEqual(page_obj.number, 1)
        self.assertEqual(page_obj.paginator.num_pages, 5)

    def test_explicit_page(self):
        request = self.factory.get("/?page=3")
        page_obj, _ = paginate(request, self.items)
        self.assertEqual(page_obj.number, 3)
        self.assertEqual(page_obj.object_list[0], 40)

    def test_invalid_page_falls_back_to_first(self):
        request = self.factory.get("/?page=notanumber")
        page_obj, _ = paginate(request, self.items)
        self.assertEqual(page_obj.number, 1)

    def test_out_of_range_page_clamped_to_last(self):
        request = self.factory.get("/?page=999")
        page_obj, _ = paginate(request, self.items)
        self.assertEqual(page_obj.number, page_obj.paginator.num_pages)

    def test_page_number_argument_overrides_querystring(self):
        request = self.factory.get("/?page=1")
        page_obj, _ = paginate(request, self.items, page_number=4)
        self.assertEqual(page_obj.number, 4)

    def test_querystring_preserves_filters_and_drops_page(self):
        request = self.factory.get("/?page=2&search=abc&risk=high")
        _, querystring = paginate(request, self.items)
        self.assertNotIn("page=", querystring)
        self.assertIn("search=abc", querystring)
        self.assertIn("risk=high", querystring)

    def test_custom_page_param(self):
        request = self.factory.get("/?inst_page=3&prof_page=1")
        page_obj, querystring = paginate(request, self.items, page_param="inst_page")
        self.assertEqual(page_obj.number, 3)
        self.assertEqual(page_obj.page_param, "inst_page")
        self.assertNotIn("inst_page=", querystring)
        self.assertIn("prof_page=1", querystring)

    def test_elided_page_range_is_attached(self):
        from django.core.paginator import Paginator

        request = self.factory.get("/")
        page_obj, _ = paginate(request, self.items)
        self.assertEqual(list(page_obj.elided_page_range), [1, 2, Paginator.ELLIPSIS, 5])
