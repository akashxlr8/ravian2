import streamlit as st
import pandas as pd
import plotly.express as px
from autogen_agentchat.agents import AssistantAgent 
from autogen_agentchat.conditions import HandoffTermination, TextMentionTermination
from autogen_agentchat.messages import HandoffMessage
from autogen_agentchat.teams import Swarm 
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
import os
from dotenv import load_dotenv
import asyncio
from logging_config import get_logger
from dataclasses import dataclass
from typing import Optional, Literal, List
from pydantic import BaseModel, Field
import re
import os
from dotenv import load_dotenv

logger = get_logger(__name__)
# Load environment variables
load_dotenv()

# Initialize the model client

model_client = AzureOpenAIChatCompletionClient(
    azure_deployment=st.secrets["AZURE_OPENAI_DEPLOYMENT"] or "",
    azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"] or "",
    model="gpt-4o-2024-05-13",
    api_version="2024-02-01",
    api_key=st.secrets["AZURE_OPENAI_API_KEY"] or "",
)

class CodeResponse(BaseModel):
    """Structured response for code generation"""
    class CodeBlock(BaseModel):
        code: str = Field(..., description="The Python code to be executed")
        code_type: Literal['visualization', 'analysis'] = Field(..., 
            description="Type of code: visualization for plots, analysis for other operations")
        observation: Optional[str] = Field(None, 
            description="explanation of the trend/pattern/insight/summary of the data based on the data and the code")

    result: CodeBlock = Field(..., 
        description="The generated code block with its type and explanation")

# Initialize Assistant Agent with visualization capabilities and structured output
Assistant = AssistantAgent(
    "Assistant",
    model_client=model_client,
    tools=[],
    description="Agent to analyze CSV data and create visualizations",
    system_message=f"""You are a data visualization expert proficient in using Plotly Express. 
    You have access to the already loaded dataframe 'df'. Your task is to generate Python code that creates insightful visualizations based on the provided dataset. 
    Ensure that your response is a JSON object adhering to the following Pydantic model:
            <Pydantic Model>
            class CodeResponse:
                result: CodeBlock
                    code: str  # The Python code to execute
                    code_type: Literal['visualization', 'analysis']  # Type of code
                    observation: Optional[str]  # trend/pattern/insight/summary of the data
            </Pydantic Model>
            - Use px.line, px.scatter, px.bar, or other appropriate plotly express charts, and px.box for distribution.
            - Utilize appropriate Plotly Express functions such as px.line, px.scatter, px.bar, etc., to create meaningful visualizations.
            - The generated code should be executable and free from errors, Use pd.concat() to combine multiple dataframes.
            - Provide a brief explanation of observed trend/pattern/insight/summary of the data.
    """
)

# Set up termination conditions
# termination = HandoffTermination(target="user") |TextMentionTermination("TERMINATE")
# team = Swarm([Assistant], termination_condition=termination, max_turns=20)

async def get_visualization_code(df, query, csv_string):
    """Get visualization code from the agent using structured output"""
    task = f"""Given this dataframe with columns
    <Columns>
    {list(df.columns)}
    </Columns>
    <Query>
    {query}
    </Query>
    Your response should be structured as specified.
    IMPORTANT: The data is already loaded as 'df'. DO NOT include pd.read_csv().
    First 5 rows of data: 
    <Data>
    {csv_string}
    </Data>
    
    Focus on the mentioned columns in the query to derive a correlation and plot the graph using Plotly.
    Ensure the code is structured as a JSON object adhering to the following Pydantic model:
    {{
        "result": {{
            "code": "import plotly.express as px\\n fig = px.scatter(df, x='Undergrad University Ranking', y='Expected Post-MBA Salary', title='Effect of Undergrad University Ranking on Expected Post-MBA Salary')", 
            "code_type": "visualization", 
            "observation": "This code creates a scatter plot showing the relationship between undergraduate university ranking and expected post-MBA salary. The plot shows a positive correlation between the two variables, indicating that higher ranked universities tend to have higher expected post-MBA salaries."
        }}
    }}
    Note:
    - Exclude fig.show() at the end of the code
    - Respond with a raw JSON object without any markdown formatting.
    - Common visualization types:
    -- px.bar → categorical comparisons (e.g., count of people in each major)
    -- px.scatter → correlations (e.g., GPA vs. Salary)
    -- px.line → trends over time (if applicable)
    -- px.box → distributions (e.g., salary distribution by major)
    -- px.pie → proportions (e.g., gender distribution)
    -- px.histogram → frequency distribution (e.g., salary distribution by major)
    -- px.area → trends over time (if applicable)
    -- px.heatmap → correlations (e.g., GPA vs. Salary)
    -- px.line_polar → trends over time (eg. salary distribution by gender)
    -- px.line_geo → trends over time (eg. salary distribution by country)
    -- px.line_mapbox → trends over time (eg. salary distribution by city)
    -- px.line_choropleth → trends over time (eg. salary distribution by country)
    -- px.line_mapbox → trends over time (eg. salary distribution by city)
            1. Heatmaps for Correlation Analysis
        Function: px.imshow(df.corr(), text_auto=True, color_continuous_scale='Viridis')
        Use Case: Visualizing correlation matrices between numerical columns.
        2. Histograms for Data Distribution
        Function: px.histogram(df, x='Salary', nbins=20, title='Salary Distribution')
        Use Case: Understanding distribution of numerical variables.
        3. Treemaps for Hierarchical Data
        Function: px.treemap(df, path=['Industry', 'Job Role'], values='Salary')
        Use Case: Displaying nested categorical data like industry vs. salary.
        4. Bubble Charts for Weighted Scatter Plots
        Function: px.scatter(df, x='GPA', y='Salary', size='Work Experience', color='Industry')
        Use Case: Showing relationships with an extra size dimension.
        5. Sunburst Charts for Multi-Level Categories
        Function: px.sunburst(df, path=['Country', 'State', 'City'], values='Population')
        Use Case: Drill-down visualization for regional or hierarchical data
    """
    
    logger.debug(f"Running task: {task}")
    task_result = await Assistant.run(task=task)
    
    messages = task_result.messages
    response_content = next((msg.content for msg in reversed(messages) 
                           if hasattr(msg, 'content') and isinstance(msg.content, str)), 
                           None)
    
    if response_content:
        try:
            # Clean up the response content by removing markdown formatting
            cleaned_content = response_content
            if "```" in cleaned_content:
                # Extract content between triple backticks
                cleaned_content = cleaned_content.split("```")[1]
                if cleaned_content.startswith("json"):
                    cleaned_content = cleaned_content[4:]  # Remove "json" prefix
                cleaned_content = cleaned_content.strip()
            
            # Parse the cleaned response into our Pydantic model
            structured_response = CodeResponse.model_validate_json(cleaned_content)
            logger.debug(f"Structured response: {structured_response}")
            return structured_response
        except Exception as e:
            logger.error(f"Error parsing structured response: {e}")
            # Fallback to basic parsing if structured parsing fails
            code = response_content.strip()
            if code.startswith("```python"):
                code = code.replace("```python", "").replace("```", "").strip()
            elif code.startswith("```"):
                code = code.replace("```", "").strip()
            
            # Create a CodeResponse object with the fallback parsing
            return CodeResponse(
                result=CodeResponse.CodeBlock(
                    code=code,
                    code_type='visualization' if 'fig' in code else 'analysis',
                    observation="Generated from fallback parsing"
                )
            )
    
    return None

def extract_figure_names(code):
    """Extracts figure variable names from the given code."""
    # Regex to find variable names assigned to Plotly figures
    figure_names = re.findall(r'(\w+)\s*=\s*px\.', code)
    return figure_names

def main():
    st.title("CSV Data Analysis & Visualization")
    st.write("Upload a CSV file to analyze and visualize its contents.")

    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            df.columns = df.columns.str.strip()
            df_5_rows = df.head(200)
            csv_string = df_5_rows.to_string(index=False)
    
            # Basic data info
            st.subheader("Dataset Overview")
            st.write(f"Number of rows: {df.shape[0]}")
            st.write(f"Number of columns: {df.shape[1]}")
            
            # Data preview
            st.subheader("Preview of Data")
            st.dataframe(df.head())

            # Add custom query input
            st.subheader("Custom Query")
            user_query = st.text_area(
                "Enter your query like : how does gender distribute in decision to pursue mba",
                placeholder="e.g., how does current job title affect choice to pursue online vs offline mba"
            )

            if st.button("Generate Response"):
                if user_query:
                    try:
                        with st.spinner("Processing your request..."):
                            response = asyncio.run(get_visualization_code(df, user_query, csv_string))
                            
                            if response and isinstance(response, CodeResponse):
                                st.subheader("Generated Python Code:")
                                st.code(response.result.code, language='python')
                                
                                if response.result.observation:
                                    st.write(response.result.observation)
                                
                                try:
                                    # Define local execution context
                                    local_vars = {'df': df, 'pd': pd, 'px': px}
                                    exec(str(response.result.code), globals(), local_vars)
                                    
                                    # Extract figure names
                                    figure_names = extract_figure_names(response.result.code)
                                    
                                    for fig_name in figure_names:
                                        if fig_name in local_vars:
                                            st.subheader(f"Generated Visualization: {fig_name}")
                                            st.plotly_chart(local_vars[fig_name])
                                    
                                except Exception as e:
                                    st.error(f"Error executing code: {e}")
                                    
                    except Exception as e:
                        st.error(f"Error processing request: {e}")

            # Automatic visualization generation
            # st.subheader("Suggested Visualizations")
            
            # visualization_queries = [
            #     "Create a histogram or bar chart for the most frequent categorical column",
            #     "Create a scatter plot using the two most correlated numerical columns",
            #     "Create a box plot showing distribution of numerical columns",
            #     "Create a pie chart for the most important categorical column"
            # ]

            # for query in visualization_queries:
            #     try:
            #         with st.spinner(f"Generating visualization: {query}"):
            #             code = asyncio.run(get_visualization_code(df, query, csv_string))
            #             if code and code.result_type == 'visualization':  # Only process visualization code
            #                 try:
            #                     local_vars = {'df': df, 'px': px}
            #                     exec(str(code), globals(), local_vars)
            #                     if 'fig' in local_vars:
            #                         st.plotly_chart(local_vars['fig'])
            #                 except Exception as e:
            #                     st.error(f"Error executing visualization code: {e}")
            #     except Exception as e:
            #         st.error(f"Error generating visualization: {e}")

        except Exception as e:
            st.error(f"An error occurred while processing the file: {e}")
    else:
        st.info("Please upload a CSV file to begin analysis.")

if __name__ == "__main__":
    main()