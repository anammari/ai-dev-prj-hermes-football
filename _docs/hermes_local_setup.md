### Why Local Works Well

* **Pre-requisite Power:** Running Hermes Agent locally requires Python 3.11+, persistent file storage, and outgoing network access to your chosen LLM endpoint (e.g., OpenRouter, OpenAI, or a local server). Your local workstation handles this with zero compute bottleneck compared to a constrained 1–2 vCPU VPS.
* **Telegram Bot Hook (No Public IP Needed):** Telegram bots communicate via **long-polling** (`getUpdates`) by default. This means your local machine makes outbound HTTPS requests to Telegram's API servers to fetch new incoming messages. You do **not** need a static IP, port forwarding, or reverse proxies (like Cloudflare Tunnels or ngrok) just to chat with your agent via Telegram.

---

### Step-by-Step Local Setup

#### 1. Install Hermes Agent

Open your terminal and install Hermes Agent natively:

```bash
# Automated installer (sets up the isolated runtime)
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

```

Alternatively, you can clone the repository directly and run it inside a standard virtual environment or container:

```bash
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
pip install -e .

```

#### 2. Configure Your LLM Endpoint

Run the interactive wizard to set your API keys:

```bash
hermes configure

```

You can point it to:

* **OpenRouter / Claude / OpenAI / Nous Portal** via an API key.
* **Local Models:** If you run Ollama or vLLM locally, you can point Hermes to `http://localhost:11434/v1` with any OpenAI-compatible client.

#### 3. Load the Tutorial's Files & RAG Knowledge Base

Pull Mariya's custom business assets from her [hermes_business_agent GitHub repository](https://github.com/MariyaSha/hermes_business_agent):

* Place her `SOUL.md` or system persona file into your Hermes profile directory (defining how the agent behaves and represents the business).
* Add the business knowledge files (the DragonDash customer support docs / FAQs) into your agent's knowledge/skills folder. Hermes natively indexes these markdown and text files for RAG retrieval during user queries.

#### 4. Hook Up Telegram

1. Open Telegram, search for `@BotFather`, and send `/newbot` to create your bot and obtain an **API Bot Token**.
2. Run Hermes's platform gateway wizard:
```bash
hermes gateway setup

```


3. Select **Telegram**, paste your bot token, and start the gateway. Hermes will begin polling Telegram and dispatching incoming user chats to your local agent logic.

---

### Local vs. VPS: The Practical Trade-Off

| Feature | Local Machine | Cloud VPS (Hostinger / Hetzner) |
| --- | --- | --- |
| **Hosting Cost** | **$0** (Free) | A$12 – A$24/month |
| **Uptime** | Only runs while your computer is on & awake | 24/7 continuous operation |
| **Development Speed** | Instant debugging, direct file editing, fast iteration | Requires SSH or remote file syncing |
| **Tool Execution** | Runs scripts and local browser tasks directly | Sandboxed within VPS resources |

Developing and testing locally first allows you to verify that the RAG indexing, custom skills, and Telegram flows perform as expected before deciding whether you need a dedicated 24/7 VPS.

For an alternative take on setting up local and modular agent architectures, you can explore the AI Agents Tutorial by freeCodeCamp. This walkthrough provides a practical foundation for running agent loops and tool orchestration entirely on your own environment without cloud hosting fees.