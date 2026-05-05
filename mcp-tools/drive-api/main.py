#!/usr/bin/env python3
"""
SafeClaw Drive API MCP Server
Uploads local files to Google Drive via a service account key file.
The credentials file is mounted at GDRIVE_CREDENTIALS_PATH (default: /opt/config/drive_credentials.json).
"""
import asyncio
import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

CREDENTIALS_PATH = os.environ.get(
    "GDRIVE_CREDENTIALS_PATH", "/opt/config/drive_credentials.json"
)

app = Server("safeclaw-drive-api")


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _resolve_folder_id(service, folder_path: str) -> str | None:
    """Walk folder_path creating missing levels. Returns the final folder ID."""
    parts = [p for p in folder_path.strip("/").split("/") if p]
    parent_id = None

    for part in parts:
        q = (
            f"name = '{part}' and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        if parent_id:
            q += f" and '{parent_id}' in parents"

        result = (
            service.files()
            .list(q=q, fields="files(id,name)", spaces="drive")
            .execute()
        )
        files = result.get("files", [])

        if files:
            parent_id = files[0]["id"]
        else:
            meta = {"name": part, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                meta["parents"] = [parent_id]
            folder = service.files().create(body=meta, fields="id").execute()
            parent_id = folder["id"]

    return parent_id


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="drive_upload_file",
            description=(
                "Upload a local file to Google Drive using a service account. "
                "Creates any missing folders in the path automatically. "
                "Returns the Drive file ID and web URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "Absolute path to the file, e.g. /data/attachments/staging/file.pdf",
                    },
                    "folder_path": {
                        "type": "string",
                        "description": "Drive folder path, e.g. SafeClaw/Attachments/Royal-Mysorian/2026-05",
                    },
                    "mimetype": {
                        "type": "string",
                        "description": "MIME type, e.g. application/pdf",
                        "default": "application/octet-stream",
                    },
                },
                "required": ["local_path", "folder_path"],
            },
        ),
        Tool(
            name="drive_find_or_create_folder",
            description="Find or create a Drive folder by path. Returns the folder ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Slash-separated path, e.g. SafeClaw/Attachments/2026-05",
                    }
                },
                "required": ["folder_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        service = _get_service()

        if name == "drive_find_or_create_folder":
            folder_id = _resolve_folder_id(service, arguments["folder_path"])
            return [TextContent(type="text", text=json.dumps({"folder_id": folder_id}))]

        if name == "drive_upload_file":
            local_path = arguments["local_path"]
            folder_path = arguments["folder_path"]
            mimetype = arguments.get("mimetype", "application/octet-stream")

            if not Path(local_path).exists():
                return [TextContent(type="text", text=json.dumps(
                    {"error": f"File not found: {local_path}"}
                ))]

            filename = Path(local_path).name
            folder_id = _resolve_folder_id(service, folder_path)

            from googleapiclient.http import MediaFileUpload

            file_meta = {"name": filename}
            if folder_id:
                file_meta["parents"] = [folder_id]

            media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
            uploaded = (
                service.files()
                .create(body=file_meta, media_body=media, fields="id,name,webViewLink")
                .execute()
            )

            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "file_id": uploaded.get("id"),
                "filename": uploaded.get("name"),
                "url": uploaded.get("webViewLink"),
                "folder_path": folder_path,
            }))]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
