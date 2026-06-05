# Siri Shortcut Notes

Siri Shortcut support is not implemented yet, but the future shortcut should call the backend `POST /chat` endpoint with the same API key auth used by curl.

Request:

```http
POST http://YOUR_BACKEND_HOST/chat
Authorization: Bearer YOUR_AGENT_API_KEY
Content-Type: application/json
```

Body:

```json
{
  "message": "Dictated text from Siri"
}
```

In Shortcuts, add these headers to the "Get Contents of URL" action:

- `Authorization`: `Bearer YOUR_AGENT_API_KEY`
- `Content-Type`: `application/json`

Keep `AGENT_API_KEY` private. Do not hard-code it into screenshots, shared shortcuts, or public docs.
