from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import requests
import json
from threading import Lock
import asyncio
import logging
from pydantic import BaseModel
from pyngrok import ngrok
from typing import List, Dict, Optional

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Zendesk API configuration
ZENDESK_SUBDOMAIN = "netsmartz3231"
ZENDESK_EMAIL = "ambikeshjha07@gmail.com"
ZENDESK_API_TOKEN = "hWL2MYxrucJaGJRkgT3YHPibYasaDQUzXcb9X0Nv"
ZENDESK_API_URL = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"

# Function to fetch agents IDs from Zendesk (agents, admins)
def fetch_all_user_ids():
    url = f"{ZENDESK_API_URL}/users.json?role[]=agent&role[]=admin"
    headers = {"Content-Type": "application/json"}
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    user_ids = []

    while url:
        response = requests.get(url, headers=headers, auth=auth)
        if response.status_code == 200:
            data = response.json()
            for user in data["users"]:
                user_ids.append(user["id"])
            url = data.get("next_page")
            logger.debug(f"Fetched {len(data['users'])} users, next page: {url}")
        else:
            logger.error(f"Failed to fetch users: {response.status_code} - {response.text}")
            break

    return user_ids

# Fetch all user IDs at startup
AGENT_IDS = fetch_all_user_ids()
logger.info(f"Fetched {len(AGENT_IDS)} user IDs: {AGENT_IDS}")

GROUP_ID = 19035713601692

# Global variables
current_ticket_id = None
message_queue: List[str] = []
message_lock = Lock()
chat_history: List[Dict[str, str]] = []

# Simple chatbot responses (used only before handover)
responses = {
    "hi": "Hello! How can I help you today?",
    "hello": "Hi there! How can I assist you?",
    "what can you do": "I can answer basic questions or hand this conversation over to a human agent. What do you need?",
    "how are you": "I’m doing great, thanks for asking! How about you?",
    "bye": "Goodbye! Let me know if you need me again.",
    "i want to talk to a human": "Sure, I’ll assign a human agent to you shortly.",
    "help": "I’m here to help! What do you need assistance with?"
}

requester_id = None

# Create a ticket and store the requester_id
def create_ticket(message: str) -> tuple[Optional[int], str]:
    global requester_id

    transcript = "Chat History Before Handover:\n"
    if chat_history:
        for entry in chat_history:
            transcript += f"{entry['source']}: {entry['message']}\n"
    else:
        transcript += "No prior chat history.\n"
    transcript += f"\nCustomer Message Triggering Handover: {message}"

    url = f"{ZENDESK_API_URL}/tickets.json"
    headers = {"Content-Type": "application/json"}
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)

    payload = {
        "ticket": {
            "subject": "Chatbot Escalation to Human Agent",
            "comment": {"body": transcript},
            "priority": "normal",
            "requester": {"name": "Chatbot User", "email": "chatbot.user@example.com"}
        }
    }
    response = requests.post(url, json=payload, headers=headers, auth=auth)
    if response.status_code == 201:
        ticket_data = response.json()
        ticket_id = ticket_data["ticket"]["id"]
        requester_id = ticket_data["ticket"]["requester_id"]
        return ticket_id, "Ticket created successfully with transcript!"
    else:
        return None, f"Failed to create ticket: {response.text}"

# Update the ticket with the correct author
def update_ticket(ticket_id: int, message: str) -> tuple[bool, str]:
    global requester_id
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
    headers = {"Content-Type": "application/json"}
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    payload = {
        "ticket": {
            "comment": {
                "body": message,
                "public": True,
                "author_id": requester_id
            }
        }
    }
    response = requests.put(url, json=payload, headers=headers, auth=auth)
    if response.status_code == 200:
        return True, "Message sent to agent successfully!"
    else:
        return False, f"Failed to send message: {response.text}"

def get_least_busy_agent(channel="support") -> tuple[int, int]:
    url = f"{ZENDESK_API_URL}/agent_availabilities"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Zendesk-Api-Version": "2023-02-01"
    }
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)

    agent_ids_str = ",".join(str(agent_id) for agent_id in AGENT_IDS)
    params = {
        "filter[agent_id]": agent_ids_str,
        "filter[channel_status]": f"{channel}:online",
    }

    response = requests.get(url, params=params, headers=headers, auth=auth)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch agent availability: {response.text}")

    data = response.json()
    agents = data.get("data", [])
    if not agents:
        raise Exception("No online agents found for channel 'support'.")

    agent_workloads = {}
    included_channels = {item["id"]: item["attributes"] for item in data.get("included", []) if item["type"] == "channels"}
    for agent in agents:
        agent_id = agent["attributes"]["agent_id"]
        channel_refs = agent["relationships"]["channels"]["data"]
        for ref in channel_refs:
            channel_data = included_channels.get(ref["id"])
            if channel_data and channel_data["name"] == channel:
                work_items = channel_data.get("work_item_count", 0)
                agent_workloads[agent_id] = work_items
                break

    if not agent_workloads:
        raise Exception(f"No workload data found for channel '{channel}'.")

    least_busy_agent = min(agent_workloads, key=agent_workloads.get)
    min_work_items = agent_workloads[least_busy_agent]
    return least_busy_agent, min_work_items

def assign_ticket(ticket_id: int) -> str:
    try:
        agent_id, work_items = get_least_busy_agent(channel="support")
        url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
        headers = {"Content-Type": "application/json"}
        auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
        payload = {
            "ticket": {
                "assignee_id": agent_id,
                "group_id": GROUP_ID
            }
        }
        response = requests.put(url, json=payload, headers=headers, auth=auth)
        if response.status_code == 200:
            return f"Ticket assigned to agent ID = {agent_id} (work items: {work_items}) successfully!"
        else:
            return f"Failed to assign ticket: {response.text}"
    except Exception as e:
        return f"Error during assignment: {str(e)}"

# Pydantic model for chat input
class ChatMessage(BaseModel):
    message: str

# Store connected WebSocket clients
connected_clients: List[WebSocket] = []

@app.post("/webhook")
async def webhook(request: Request):
    global current_ticket_id, message_queue
    data = await request.json()
    logger.debug(f"Webhook received: {data}")

    ticket_id = data.get('ticket_id')
    if not ticket_id or ticket_id != str(current_ticket_id):
        logger.debug(f"Ignoring webhook - ticket_id {ticket_id} does not match current_ticket_id {current_ticket_id}")
        return {"status": "ignored"}

    comment = data.get('ticket', {}).get('comment', {}).get('body')
    author_role = data.get('ticket', {}).get('comment', {}).get('author_role')

    if comment and author_role != "End-user":
        with message_lock:
            message = f"{author_role}: {comment}"
            message_queue.append(message)
            logger.debug(f"Added to queue: {message}")
            # Broadcast to all connected clients
            for client in connected_clients[:]:  # Use a copy to avoid modification during iteration
                try:
                    await client.send_json({"response": message})
                except Exception as e:
                    logger.error(f"Failed to send to client: {e}")
                    connected_clients.remove(client)
    else:
        logger.debug(f"Skipping - no valid comment or author_role: {data}")

    return {"status": "received"}

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.debug("WebSocket client connected")
    try:
        while True:
            # Keep the connection alive; we broadcast from webhook
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected")
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        await websocket.close()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    global current_ticket_id, message_queue, chat_history
    if not current_ticket_id:
        message_queue.clear()
        chat_history.clear()
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def chat(message: ChatMessage):
    global current_ticket_id, requester_id, chat_history
    user_input = message.message.strip()
    if not user_input:
        return {"response": "Please say something!"}

    chat_history.append({"source": "User", "message": user_input})

    if current_ticket_id:
        success, response = update_ticket(current_ticket_id, user_input)
        return {"response": response}

    if user_input.lower() == "human_handover":
        ticket_id, create_response = create_ticket(user_input)
        if ticket_id:
            current_ticket_id = ticket_id
            assign_response = assign_ticket(ticket_id)
            response = f"{create_response} Ticket ID: {ticket_id}. {assign_response}"
        else:
            response = create_response
    else:
        response = responses.get(user_input.lower(), "I’m not sure how to respond to that. Ask for a human agent by clicking 'Talk to agent' button above")
        chat_history.append({"source": "Bot", "message": response})
    return {"response": response}

if __name__ == "__main__":
    import uvicorn
    ngrok.set_auth_token("2uWutPRb2hxN9nOARUgvhaXPzo5_3nAte2Mhf18oL8Xg3qjPd")
    public_url = ngrok.connect(8000).public_url
    print(f"ngrok tunnel opened at: {public_url}")
    print(f"Set your Zendesk webhook to: {public_url}/webhook")
    uvicorn.run(app, host="0.0.0.0", port=8000)
 
