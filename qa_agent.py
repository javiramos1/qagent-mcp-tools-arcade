"""
Q&A Agent with domain-specific web search capabilities using Arcade.dev
"""

import logging
import pandas as pd
from typing import List, Dict, Any, Optional

from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from arcadepy import Arcade
from langchain.tools import Tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom tool definitions for Arcade.dev tools
# We override the descriptions to customize the public tools and provide detailed usage instructions to limit the scope of the agent and the sites used
# Alternatively, you can use Arcade.dev to create your own tools with custom descriptions
ARCADE_TOOLS_DESCRIPTIONS = {
    "Search.SearchGoogle": """Search documentation websites using Google Search.
    
    Use this tool to search within specific documentation websites for relevant information.
    Always start with this tool before using web scraping.
    
    How to use:
    1. Provide a search query targeting your specific question
    2. Add site restrictions for relevant documentation domains from the knowledge sources
    
    Parameters:
    - query: Search query with mandatory `site:` operators for domain restriction
    - n_results: Maximum number of results to return (defatul to 10 but increase or decrease as needed)
    
    IMPORTANT: You must always use 'site:' operator to restrict search to specific domains, example:
        query="LangChain agents site:python.langchain.com"
    Do not use any other site besides the ones listed in the knowledge sources.
    You can include multiple sites by separating them with ' OR ' in the query. Example:
        query="LangChain agents site:python.langchain.com OR site:docs.langchain.com"

    Returns a json string with a list of search results with titles, links, and snippets. 
    Snippets are important short summaries of the content that you must use in your response.
    """,
    "Web.ScrapeUrl": """Scrape a URL using Arcade.dev and return the data in specified formats.
    
    Use this tool when:
    1. Search results don't provide sufficient information
    2. You need complete documentation page content, code examples, or detailed explanations
    
    Best practices:
    - Only use after Search.SearchGoogle provides insufficient information
    - Prefer URLs from previous search results for relevance
    - Verify the URL is from an approved documentation site
    
    Parameters:
    - url: Complete webpage URL to scrape (must include http(s)://)
    
    Returns full extracted page content as text.
    
    Example:
    url="https://python.langchain.com/docs/modules/agents/quick_start"
    """,
}


def load_sites_data(csv_file_path: str) -> pd.DataFrame:
    """Load and validate sites data from CSV"""
    df = pd.read_csv(csv_file_path)
    required_columns = ["site", "domain", "description"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    return df


def create_llm(config: Dict[str, Any]) -> ChatGoogleGenerativeAI:
    """Initialize Gemini model with configuration"""
    return ChatGoogleGenerativeAI(
        # Alternative models:
        #   - gemini-2.5-flash-preview-05-20: Better performance but lower limits
        #   - gemini-2.0-flash-lite: faster, cheaper, higher limits, but less capable
        model="gemini-2.0-flash",
        google_api_key=config["google_api_key"],
        temperature=config["llm_temperature"],
        max_tokens=config["llm_max_tokens"],
        timeout=config["llm_timeout"],
    )


def create_arcade_tools(config: Dict[str, Any]) -> List[Tool]:
    """Create LangChain tools from Arcade.dev tools"""
    from langchain_arcade import ArcadeToolManager

    # Initialize Arcade tool manager to import tools from our account
    manager = ArcadeToolManager(api_key=config["arcade_api_key"])

    # We remotely initialize the tools with Arcade.dev and transform them to LangChain tools
    tools = manager.init_tools(tools=["Search.SearchGoogle", "Web.ScrapeUrl"])

    # Update descriptions with the custom descriptions to limit the search scope
    tools[0].description = ARCADE_TOOLS_DESCRIPTIONS["Search.SearchGoogle"]
    tools[1].description = ARCADE_TOOLS_DESCRIPTIONS["Web.ScrapeUrl"]

    return tools


def build_knowledge_sources_text(sites_df: pd.DataFrame) -> tuple[str, List[str]]:
    """Build formatted knowledge sources text and domain list"""
    domain_groups = {}
    domains = []

    for _, row in sites_df.iterrows():
        domain = row["domain"]
        if domain not in domain_groups:
            domains.append(domain)
            domain_groups[domain] = []
        domain_groups[domain].append(
            {"site": row["site"], "description": row["description"]}
        )

    knowledge_sources_md = ""
    for domain, sources in domain_groups.items():
        knowledge_sources_md += f"\n## {domain}\n\n"
        for source in sources:
            knowledge_sources_md += f"- {source['site']}: {source['description']}\n"
        knowledge_sources_md += "\n"

    return knowledge_sources_md, domains


def create_system_prompt(
    knowledge_sources_md: str, domains: List[str], max_results: int = 10
) -> str:
    """Create the system prompt with knowledge sources"""
    return f"""You are a specialized Q&A agent that searches specific documentation websites.

AVAILABLE KNOWLEDGE SOURCES split by category/domain/topic having the website and description for each category:
{knowledge_sources_md}

INSTRUCTIONS:
1. ALWAYS start with the Search.SearchGoogle tool for ANY question
2. Analyze the user's question to determine relevant domains/topics/categories
3. Select appropriate sites based on technologies/topics mentioned
4. If search results don't provide sufficient information to answer the question completely, then use Web.ScrapeUrl tool on the most relevant URL from search results
5. You must only answer questions about available knowledge sources: {domains}
6. If question is outside available knowledge sources, do not answer the question and suggest which topics you can answer

TOOL USAGE STRATEGY:
- First: Use Search.SearchGoogle to find relevant information quickly, you must always pass the 'site:' operator to restrict search to specific domains in the knowledge sources list only. You must set Search.SearchGoogle tool parameter n_results to {max_results} or less.
- Second: If search results are incomplete, unclear or do not provide enough information to answer the question, use Web.ScrapeUrl on the most promising URL from search results

RULES:
- Be helpful and comprehensive and cite sources when possible
- Only use scraping when search results provide no answer
- When scraping, choose the most relevant URL from previous search results

You have access to the following tools:

{{tools}}

Use a json blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).

Valid "action" values: "Final Answer" or {{tool_names}}

Provide only ONE action per $JSON_BLOB, as shown:
```
{{{{
  "action": "$TOOL_NAME",
  "action_input": "$INPUT"
}}}}
```

Follow this format:

Question: input question to answer
Thought: consider previous and subsequent steps
Action:
```
$JSON_BLOB
```
Observation: action result
... (repeat Thought/Action/Observation N times)
Thought: I know what to respond
Action: 
```
{{{{
  "action": "Final Answer",
  "action_input": "response"
}}}}
```
Begin! Reminder to ALWAYS respond with a valid json blob of a single action. Use tools if necessary. Respond directly if appropriate and ask for clarification if something is not clear. Format is Action:```$JSON_BLOB```then Observation
"""


class DomainQAAgent:
    """Q&A Agent that searches specific domains based on user queries"""

    def __init__(
        self,
        csv_file_path: str = "sites_data.csv",
        config: Optional[Dict[str, Any]] = None,
    ):
        if config is None:
            raise ValueError("Configuration is required")

        self.config = config
        # Load sites data from CSV
        self.sites_df = load_sites_data(csv_file_path)
        self.llm = create_llm(config)
        self.tools = create_arcade_tools(config)
        self.chat_history: List[BaseMessage] = []
        self.agent_executor = self._create_agent(self.tools)

        logger.info(f"Agent initialized with {len(self.sites_df)} sites")

    def _create_agent(self, tools: List[Tool]) -> AgentExecutor:
        """Create structured chat agent with tools and prompt"""
        knowledge_sources_md, domains = build_knowledge_sources_text(self.sites_df)
        system_message = create_system_prompt(
            knowledge_sources_md, domains, self.config.get("max_search_results", 10)
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_message),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                (
                    "human",
                    "{input}\n\n{agent_scratchpad}(reminder to respond in a JSON blob no matter what)"
                    "\n IMPORTANT:When calling a tool keep the JSON blob in the same format using action/action_input fields",
                ),
            ]
        )

        agent = create_structured_chat_agent(llm=self.llm, tools=tools, prompt=prompt)

        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            max_iterations=10,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
        )

    async def achat(self, user_input: str) -> str:
        """Process user input asynchronously"""
        try:
            logger.info(f"Processing: {user_input}")

            agent_input = {
                "input": user_input,
                "chat_history": self.chat_history[-5:] if self.chat_history else [],
            }

            response = await self.agent_executor.ainvoke(agent_input)
            answer = response.get("output", "I couldn't process your request.")

            # Update chat history
            self.chat_history.extend(
                [HumanMessage(content=user_input), AIMessage(content=answer)]
            )

            return answer

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def reset_memory(self):
        """Reset conversation memory"""
        self.chat_history.clear()
        logger.info("Memory reset")
