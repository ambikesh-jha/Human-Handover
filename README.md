# Zendesk AI Chatbot with Human Handover

An intelligent customer support chatbot that integrates seamlessly with Zendesk. Features a rule-based bot for initial queries, automatic escalation to human agents, intelligent workload-based agent assignment, and real-time communication via WebSockets.

## Features

### Intelligent Chatbot
- **Rule-Based Responses**: Handles common queries (hi, hello, help, etc.)
- **Conversation Memory**: Maintains chat history for context
- **Human Handover**: Triggers escalation with "human_handover" command

### Zendesk Integration
- **Automatic Ticket Creation**: Creates tickets with full chat transcripts
- **Agent Assignment**: Assigns tickets to least busy agents based on workload
- **Webhook Support**: Receives agent responses in real-time
- **Thread-Safe Messaging**: Manages concurrent message queues

### Real-Time Communication
- **WebSocket Streaming**: Live updates to connected clients
- **Message Broadcasting**: Agent responses sent to all connected users
- **Connection Management**: Handles client disconnections gracefully

### Deployment Features
- **ngrok Tunneling**: Exposes local server for easy testing
- **Debug Logging**: Comprehensive logging for troubleshooting
- **Error Handling**: Graceful failure with user-friendly messages

## How It Works

### Phase 1: Chatbot Mode
1. User sends messages to the bot
2. Bot responds with predefined answers
3. Chat history is preserved

### Phase 2: Human Handover
1. User types "human_handover" or clicks button
2. System creates Zendesk ticket with full transcript
3. Assigns to least busy agent based on workload
4. Switches to ticket mode for all subsequent messages

### Phase 3: Agent Communication
1. All user messages appended to ticket as comments
2. Agent responses received via webhook
3. Responses broadcast to connected WebSocket clients
4. Real-time conversation between user and agent

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/zendesk-chatbot.git
cd zendesk-chatbot

# Install dependencies
pip install fastapi uvicorn jinja2 requests pyngrok pydantic

# Set up directory structure
mkdir -p static templates
