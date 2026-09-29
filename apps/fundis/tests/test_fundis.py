from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.core.testing import FAR_AWAY, MWENGE, SINZA, make_category, make_fundi, make_user
from apps.fundis.models import FundiProfile


class BecomeFundiTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.category = make_category()

    def test_create_add_service_and_activate(self):
        response = self.client.post(
            "/api/v1/fundi/profile/",
            {"business_name": "Juma Electric", "latitude": SINZA[0], "longitude": SINZA[1]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "draft")
        self.assertAlmostEqual(response.data["location"]["latitude"], SINZA[0])

        # Can't activate without a service.
        self.assertEqual(self.client.post("/api/v1/fundi/profile/activate/").status_code, 400)

        response = self.client.post(
            "/api/v1/fundi/services/",
            {"category_id": str(self.category.id), "pricing_type": "callout", "starting_price_tzs": 10000},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        response = self.client.post("/api/v1/fundi/profile/activate/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "active")
        # Active but not identity-verified: not visible to clients yet.
        self.assertFalse(response.data["is_discoverable"])

    def test_only_one_profile_per_user(self):
        self.client.post("/api/v1/fundi/profile/", {"business_name": "A"}, format="json")
        response = self.client.post("/api/v1/fundi/profile/", {"business_name": "B"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_service_refused(self):
        make_fundi(self.user, category=self.category)
        response = self.client.post(
            "/api/v1/fundi/services/", {"category_id": str(self.category.id)}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class SearchTests(APITestCase):
    url = "/api/v1/fundis/search/"

    def setUp(self):
        self.electrical = make_category("electrical")
        self.solar = make_category("solar", parent=self.electrical)
        self.plumbing = make_category("plumbing")

    def _search(self, point=MWENGE, **params):
        return self.client.get(self.url, {"lat": point[0], "lng": point[1], **params})

    def test_finds_verified_fundi_nearby_without_exposing_location(self):
        fundi = make_fundi(category=self.electrical)
        response = self._search(radius_km=5, category="electrical")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual([r["id"] for r in results], [str(fundi.id)])
        self.assertAlmostEqual(results[0]["distance_km"], 3.3, delta=0.3)
        self.assertNotIn("base_location", results[0])
        self.assertNotIn("location", results[0])

    def test_parent_category_includes_subcategory_fundis(self):
        fundi = make_fundi(category=self.solar)
        ids = [r["id"] for r in self._search(category="electrical").data["results"]]
        self.assertEqual(ids, [str(fundi.id)])

    def test_filters_out_other_categories(self):
        make_fundi(category=self.plumbing)
        self.assertEqual(self._search(category="electrical").data["results"], [])

    def test_excludes_unverified_paused_unavailable_and_far(self):
        make_fundi(verified=False)
        make_fundi(active=False)
        make_fundi(is_available=False)
        make_fundi(location=FAR_AWAY)
        suspended = make_fundi()
        FundiProfile.objects.filter(pk=suspended.pk).update(status=FundiProfile.Status.SUSPENDED)
        self.assertEqual(self._search(radius_km=50).data["results"], [])

    def test_respects_fundi_service_radius(self):
        make_fundi(radius_km=2)  # client is ~3.3 km away
        self.assertEqual(self._search(radius_km=10).data["results"], [])

    def test_orders_by_distance(self):
        far = make_fundi(location=SINZA)
        near = make_fundi(location=MWENGE)
        ids = [r["id"] for r in self._search(radius_km=10).data["results"]]
        self.assertEqual(ids, [str(near.id), str(far.id)])

    def test_public_detail_hides_non_discoverable(self):
        fundi = make_fundi()
        self.assertEqual(self.client.get(f"/api/v1/fundis/{fundi.id}/").status_code, 200)
        User.objects.filter(pk=fundi.user_id).update(identity_status="reverification_required")
        self.assertEqual(self.client.get(f"/api/v1/fundis/{fundi.id}/").status_code, 404)

    def test_requires_coordinates(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)
