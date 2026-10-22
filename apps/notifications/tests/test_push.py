from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.core.testing import image_file, make_fundi, make_user
from apps.notifications.models import Broadcast, Device, Notification
from apps.notifications.services import notify

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
SEND = "apps.notifications.push.ConsolePushBackend.send"


@override_settings(STORAGES=STORAGES)
class PushTests(APITestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True, full_name="Admin")
        self.client_user = make_user(full_name="Peter", preferred_language="en")
        self.fundi_user = make_user(full_name="Juma", preferred_language="sw")
        make_fundi(self.fundi_user)

    def test_device_registration_moves_between_accounts(self):
        self.client.force_authenticate(self.client_user)
        r = self.client.post("/api/v1/notifications/devices/", {"token": "tok-1", "platform": "android"})
        self.assertEqual(r.status_code, 204)
        self.client.force_authenticate(self.fundi_user)
        r = self.client.post("/api/v1/notifications/devices/", {"token": "tok-1", "platform": "android"})
        self.assertEqual(Device.objects.get(token="tok-1").user, self.fundi_user)
        self.client.delete("/api/v1/notifications/devices/", {"token": "tok-1"})
        self.assertFalse(Device.objects.exists())

    def test_notify_pushes_after_commit(self):
        Device.objects.create(user=self.client_user, token="tok-2")
        with mock.patch(SEND, return_value=True) as send, self.captureOnCommitCallbacks(execute=True):
            notify(self.client_user, "booking.cancelled", ref="FF-1")
        self.assertEqual(send.call_count, 1)

    def test_dead_tokens_are_forgotten(self):
        Device.objects.create(user=self.client_user, token="dead")
        with mock.patch(SEND, return_value=False), self.captureOnCommitCallbacks(execute=True):
            notify(self.client_user, "booking.cancelled", ref="FF-1")
        self.assertFalse(Device.objects.exists())

    def test_push_failure_never_breaks_notify(self):
        Device.objects.create(user=self.client_user, token="boom")
        with mock.patch(SEND, side_effect=RuntimeError("fcm down")), self.captureOnCommitCallbacks(execute=True):
            notify(self.client_user, "booking.cancelled", ref="FF-1")
        self.assertEqual(Notification.objects.count(), 1)

    def _payload(self, **extra):
        return {
            "audience": "all", "title_sw": "Habari", "title_en": "News", "body_sw": "Karibu sana", "body_en": "Welcome",
            **extra,
        }

    def test_only_staff_can_broadcast(self):
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.post("/api/v1/admin/broadcasts/", self._payload()).status_code, 403)

    def test_broadcast_fans_out_in_each_language_with_image(self):
        Device.objects.create(user=self.client_user, token="a")
        Device.objects.create(user=self.fundi_user, token="b")
        self.client.force_authenticate(self.staff)
        with mock.patch(SEND, return_value=True) as send:
            r = self.client.post(
                "/api/v1/admin/broadcasts/", self._payload(image=image_file("promo.jpg"), link="/pro"), format="multipart"
            )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["recipients"], r.data["pushed"]), (2, 2))
        self.assertTrue(r.data["image"])
        titles = {c.args[1] for c in send.call_args_list}
        self.assertEqual(titles, {"Habari", "News"})
        self.assertTrue(all(c.args[3].startswith("http") for c in send.call_args_list))  # absolute image URL
        mine = Notification.objects.get(user=self.fundi_user)
        self.assertEqual((mine.title, mine.data["link"]), ("Habari", "/pro"))
        self.assertTrue(mine.image)
        self.assertFalse(Notification.objects.filter(user=self.staff).exists())

    def test_audience_targets_fundis_or_clients(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post("/api/v1/admin/broadcasts/", self._payload(audience="fundis"))
        self.assertEqual(r.data["recipients"], 1)
        r = self.client.post("/api/v1/admin/broadcasts/", self._payload(audience="clients"))
        self.assertEqual(r.data["recipients"], 1)
        self.assertEqual(Broadcast.objects.count(), 2)
        counts = self.client.get("/api/v1/admin/broadcasts/").data["audiences"]
        self.assertEqual((counts["fundis"], counts["clients"], counts["all"]), (1, 1, 2))

    def test_test_send_goes_only_to_staff(self):
        Device.objects.create(user=self.staff, token="s")
        Device.objects.create(user=self.client_user, token="c")
        self.client.force_authenticate(self.staff)
        with mock.patch(SEND, return_value=True) as send:
            r = self.client.post("/api/v1/admin/broadcasts/?test=1", self._payload())
        self.assertEqual((r.status_code, r.data["pushed"], send.call_count), (200, 1, 1))
        self.assertFalse(Broadcast.objects.exists())

    def test_validation(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.post("/api/v1/admin/broadcasts/", self._payload(link="https://evil")).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/admin/broadcasts/", self._payload(title_en="")).status_code, 400)
