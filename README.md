# Love Diary - Agent Service

ASI-powered character agents with dynamic loading, memory management, and PostgreSQL persistence.

## Overview

The Agent Service manages character agents that power conversations in Love Diary. Each agent:
- Has a unique personality based on NFT character traits
- Generates a background story using ASI-1 Mini
- Maintains conversation memory with vector search
- Dynamically loads/hibernates based on activity
- Persists state to PostgreSQL database (Supabase)

## Architecture

```
┌─────────────────────────────────────┐
│      FastAPI Server (Port 8000)     │
│  - POST /agent/{id}/create          │
│  - POST /agent/{id}/message         │
│  - GET  /health                     │
└──────────────┬──────────────────────┘
               │
               ↓
┌──────────────────────────────────────┐
│         Agent Manager                │
│  - Dynamic agent loading             │
│  - Keep 10-30 active in memory       │
│  - Hibernate after 1 hour idle       │
└──────────────┬───────────────────────┘
               │
               ↓
┌───────────────────────────────────────┐
│    CharacterAgent Instances           │
│  - Process messages with ASI-1 Mini   │
│  - Manage conversation memory         │
│  - Generate daily diaries             │
└──────────────┬────────────────────────┘
               │
         ┌─────┴─────┬──────────────┐
         ↓           ↓              ↓
   PostgreSQL  ASI-1 Mini    Base Blockchain
   (Storage)     (LLM)          (NFT Data)
```

## Features

- **Dynamic Agent Loading**: Only keeps active agents in memory, hibernates idle ones
- **Backstory Generation**: Creates rich background stories on first chat
- **Memory System**: Stores daily diary entries with semantic search
- **State Persistence**: Agent state survives restarts via PostgreSQL
- **Service-to-Service Auth**: Secure communication with backend
- **Health Monitoring**: Built-in health checks and logging

## Requirements

- Python 3.11+
- Docker & Docker Compose (for deployment)
- PostgreSQL database (Supabase recommended)
- ASI-1 Mini API key
- Base Sepolia RPC access

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/yourorg/love-diary-agents.git
cd love-diary-agents

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### 2. Install Dependencies (Local Development)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Locally

```bash
# Make sure .env is configured
python -m agent_service.main

# Or use uvicorn directly
uvicorn agent_service.main:app --reload
```

Service will be available at `http://localhost:8000`

### 4. Run with Docker

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## API Endpoints

### POST /agent/{character_id}/create

Create a new agent with backstory generation.

**Headers:**
- `Authorization: Bearer {AGENT_SERVICE_SECRET}`
- `X-Player-Address: {wallet_address}`

**Request Body:**
```json
{
  "playerName": "Alex",
  "playerGender": "Male"
}
```

**Response:**
```json
{
  "status": "created",
  "firstMessage": "Hi Alex! I'm Emma...",
  "backstorySummary": "I grew up in...",
  "agentAddress": "agent://character_123"
}
```

### POST /agent/{character_id}/message

Send a message to an agent.

**Headers:**
- `Authorization: Bearer {AGENT_SERVICE_SECRET}`
- `X-Player-Address: {wallet_address}`

**Request Body:**
```json
{
  "message": "How was your day?",
  "playerName": "Alex",
  "timestamp": 1728750000
}
```

**Response:**
```json
{
  "response": "It was wonderful! I...",
  "timestamp": 1728750005,
  "affectionChange": 2,
  "agentStatus": "active"
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "active_agents": 23,
  "hibernated_agents": 150,
  "total_messages_processed": 15420,
  "uptime_seconds": 86400
}
```

## Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_SERVICE_SECRET` | Yes | - | Shared secret for auth |
| `CHARACTER_NFT_ADDRESS` | Yes | - | NFT contract address |
| `ASI_MINI_API_KEY` | Yes | - | ASI-1 Mini API key |
| `DATABASE_URL` | Yes | - | PostgreSQL connection URL |
| `BASE_RPC_URL` | No | sepolia.base.org | Base RPC URL |
| `AGENT_IDLE_TIMEOUT` | No | 3600 | Idle time before hibernation (seconds) |
| `MAX_ACTIVE_AGENTS` | No | 50 | Max agents in memory |

See `.env.example` for complete list.

## Deployment (VPS)

### Recommended: Hetzner CX31 ($13/month)
- 4GB RAM, 2 vCPU, 80GB SSD
- Ubuntu 22.04

```bash
# 1. Provision VPS and SSH in
ssh root@your-vps-ip

# 2. Install Docker
apt update && apt install docker.io docker-compose -y

# 3. Clone repo
git clone https://github.com/yourorg/love-diary-agents.git
cd love-diary-agents

# 4. Configure environment
nano .env  # Add your keys

# 5. Start service
docker-compose up -d

# 6. Configure nginx reverse proxy (optional)
# See docs/nginx-setup.md
```

### SSL with Let's Encrypt

```bash
apt install nginx certbot python3-certbot-nginx -y

# Configure nginx
nano /etc/nginx/sites-available/love-diary-agents

# Example config:
server {
    listen 80;
    server_name agents.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Enable site
ln -s /etc/nginx/sites-available/love-diary-agents /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# Get SSL certificate
certbot --nginx -d agents.yourdomain.com
```

## Monitoring

### Logs

```bash
# Docker logs
docker-compose logs -f agent-service

# Or check log files (if volume mounted)
tail -f logs/agent-service.log
```

### Metrics

Access `/health` endpoint for service metrics:

```bash
curl http://localhost:8000/health
```

## Development

### Running Tests

```bash
pytest
```

### Code Structure

```
agent_service/
├── main.py               # FastAPI app
├── agent_manager.py      # Agent lifecycle management
├── character_agent.py    # Individual agent logic
├── asi_mini_client.py    # LLM client
├── postgres_storage.py   # Database client
├── blockchain_client.py  # NFT contract client
└── config.py             # Configuration
```

### Adding New Features

1. **New LLM Provider**: Implement in `asi_mini_client.py`
2. **New Storage Backend**: Implement in `postgres_storage.py`
3. **New Agent Behavior**: Modify `character_agent.py`

## Troubleshooting

### Agent won't wake up

- Check database connection: Test with `psql ${DATABASE_URL}`
- Check agent state exists in database
- Review logs for hibernation errors

### High memory usage

- Reduce `MAX_ACTIVE_AGENTS` in .env
- Lower `AGENT_IDLE_TIMEOUT` for faster hibernation
- Check for memory leaks in logs

### Slow response times

- Check ASI-1 Mini API latency
- Verify database query performance
- Consider caching frequently accessed data

## License

MIT

## Support

For issues and questions:
- GitHub Issues: https://github.com/yourorg/love-diary-agents/issues
- Documentation: https://docs.lovediary.game
