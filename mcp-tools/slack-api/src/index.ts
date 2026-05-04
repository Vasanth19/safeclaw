import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { WebClient } from "@slack/web-api";
import { z } from "zod";

const token = process.env.SLACK_BOT_TOKEN;
if (!token) {
  throw new Error("SLACK_BOT_TOKEN environment variable is required");
}

const slack = new WebClient(token);

const server = new Server(
  {
    name: "safeclaw-slack-api",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

/**
 * Tool definitions.
 * We enforce the Reader/Actor split by checking an environment variable
 * SLACK_MCP_MODE (either 'reader' or 'actor').
 */
const MODE = (process.env.SLACK_MCP_MODE || "reader").toLowerCase();

server.setRequestHandler(ListToolsRequestSchema, async () => {
  const tools = [];

  if (MODE === "reader") {
    tools.push(
      {
        name: "slack_list_channels",
        description: "List public channels in the workspace",
        inputSchema: {
          type: "object",
          properties: {
            types: { type: "string", description: "public_channel,private_channel" },
          },
        },
      },
      {
        name: "slack_get_channel_history",
        description: "Fetch message history from a channel",
        inputSchema: {
          type: "object",
          properties: {
            channel_id: { type: "string" },
            limit: { type: "number", default: 20 },
            oldest: { type: "string", description: "Timestamp" },
          },
          required: ["channel_id"],
        },
      },
      {
        name: "slack_get_user_info",
        description: "Get profile info for a Slack user ID",
        inputSchema: {
          type: "object",
          properties: {
            user_id: { type: "string" },
          },
          required: ["user_id"],
        },
      }
    );
  }

  if (MODE === "actor") {
    tools.push(
      {
        name: "slack_send_message",
        description: "Post a message to a channel or DM",
        inputSchema: {
          type: "object",
          properties: {
            channel_id: { type: "string" },
            text: { type: "string" },
            thread_ts: { type: "string" },
          },
          required: ["channel_id", "text"],
        },
      },
      {
        name: "slack_upload_file",
        description: "Upload a file to Slack",
        inputSchema: {
          type: "object",
          properties: {
            channel_id: { type: "string" },
            file_path: { type: "string" },
            title: { type: "string" },
            initial_comment: { type: "string" },
          },
          required: ["channel_id", "file_path"],
        },
      }
    );
  }

  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "slack_list_channels": {
        const res = await slack.conversations.list({ types: args?.types as string || "public_channel" });
        return { content: [{ type: "text", text: JSON.stringify(res.channels) }] };
      }
      case "slack_get_channel_history": {
        const res = await slack.conversations.history({
          channel: args?.channel_id as string,
          limit: args?.limit as number,
          oldest: args?.oldest as string,
        });
        return { content: [{ type: "text", text: JSON.stringify(res.messages) }] };
      }
      case "slack_get_user_info": {
        const res = await slack.users.info({ user: args?.user_id as string });
        return { content: [{ type: "text", text: JSON.stringify(res.user) }] };
      }
      case "slack_send_message": {
        const res = await slack.chat.postMessage({
          channel: args?.channel_id as string,
          text: args?.text as string,
          thread_ts: args?.thread_ts as string,
        });
        return { content: [{ type: "text", text: JSON.stringify(res) }] };
      }
      case "slack_upload_file": {
        // Simple upload implementation
        const fs = await import("fs");
        const res = await slack.files.uploadV2({
          channel_id: args?.channel_id as string,
          file: fs.createReadStream(args?.file_path as string),
          filename: args?.file_path as string,
          title: args?.title as string,
          initial_comment: args?.initial_comment as string,
        });
        return { content: [{ type: "text", text: JSON.stringify(res) }] };
      }
      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error: any) {
    return {
      isError: true,
      content: [{ type: "text", text: error.message || String(error) }],
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`SafeClaw Slack MCP running in ${MODE} mode`);
}

main().catch(console.error);
