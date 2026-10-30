import os
import unittest
from unittest.mock import AsyncMock, patch

import main


class FakeTokenResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"access_token": "orders-token"}


class FakeGraphResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class OrderGraphCredentialTests(unittest.IsolatedAsyncioTestCase):
    def test_dedicated_credentials_take_precedence(self):
        environment = {
            "MS_TENANT_ID": "shared-tenant",
            "MS_CLIENT_ID": "shared-client",
            "MS_CLIENT_SECRET": "shared-secret",
            "ORDER_GRAPH_TENANT_ID": "orders-tenant",
            "ORDER_GRAPH_CLIENT_ID": "orders-client",
            "ORDER_GRAPH_CLIENT_SECRET": "orders-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                main.order_graph_credentials(),
                ("orders-tenant", "orders-client", "orders-secret"),
            )
            self.assertTrue(main.order_graph_configured())

    def test_shared_credentials_are_a_backward_compatible_fallback(self):
        environment = {
            "MS_TENANT_ID": "shared-tenant",
            "MS_CLIENT_ID": "shared-client",
            "MS_CLIENT_SECRET": "shared-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                main.order_graph_credentials(),
                ("shared-tenant", "shared-client", "shared-secret"),
            )
            self.assertTrue(main.order_graph_configured())

    async def test_token_request_uses_dedicated_credentials(self):
        client = AsyncMock()
        client.post.return_value = FakeTokenResponse()
        environment = {
            "ORDER_GRAPH_TENANT_ID": "orders-tenant",
            "ORDER_GRAPH_CLIENT_ID": "orders-client",
            "ORDER_GRAPH_CLIENT_SECRET": "orders-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            token = await main.order_graph_access_token(client)

        self.assertEqual(token, "orders-token")
        client.post.assert_awaited_once()
        _, kwargs = client.post.await_args
        self.assertEqual(kwargs["data"]["client_id"], "orders-client")
        self.assertEqual(kwargs["data"]["client_secret"], "orders-secret")

    async def test_orders_folder_can_be_an_inbox_child(self):
        client = AsyncMock()
        client.get.side_effect = [
            FakeGraphResponse({"value": []}),
            FakeGraphResponse({"value": [{"id": "orders-id", "displayName": "Orders"}]}),
            FakeGraphResponse({"value": [{"id": "message-id", "subject": "Test"}]}),
        ]

        messages = await main.graph_order_folder_messages(
            client, "orders-token", "matthew@bullfrog.net"
        )

        self.assertEqual(messages[0]["id"], "message-id")
        second_url = client.get.await_args_list[1].args[0]
        self.assertIn("/mailFolders/inbox/childFolders", second_url)
        third_url = client.get.await_args_list[2].args[0]
        self.assertIn("/mailFolders/orders-id/messages", third_url)


if __name__ == "__main__":
    unittest.main()
