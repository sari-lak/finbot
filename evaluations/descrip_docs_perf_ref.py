import sys
import os
import random

from langchain_core.runnables import RunnableLambda
from langsmith.schemas import Example, Run
from langsmith.evaluation import evaluate

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from finbot.rag_chain_agent import RAGChain
from finbot.rag_chain_route import RAGChainRoute
from finbot.langsmith_eval import FinbotEval

langsmith_eval = FinbotEval()

import os

# Disable parallelism for huggingface/tokenizers
os.environ["TOKENIZERS_PARALLELISM"] = "false"

collection_name = "all_docs_kb_clean_inv"
rag_chain = RAGChain(collection_name)
route_chain = RAGChainRoute(collection_name)

# Load the vector store associated to the RAGChain
vectorstore = rag_chain.loaded_vectorstore
rag_chain.create_chains()  # Initialize all the chains

# Extract the unique metadata values from the collection
metadata = langsmith_eval.inspect_collection_upload(collection_name, point_verbose = False)

# Capture the retrieved documents for a "GOOD" run
def capture_and_run_chain(inputs, retriever_chain, main_chain):
    # Capture the retrieval documents by wrapping the general chain
    def capture_documents(inputs):
        # Extract the question and top_k values from the inputs dictionary
        question = inputs["question"]

        # Capture the documents retrieved during the invocation
        # Use the passed retriever_chain with the float value of top_k and the string value of question
        documents = retriever_chain.invoke(question)

        # Use the passed main_chain and invoke it with the inputs dictionary
        final_output = main_chain.invoke(question)

        # Return both final output and retrieved documents
        return {
            "final_output": final_output,
            "retrieved_docs": documents
        }

    # Wrap in a RunnableLambda to integrate with your chain execution
    wrapped_chain = RunnableLambda(capture_documents)
    return wrapped_chain.invoke(inputs)

# Create new dataset
# Create a dataset for the Investment Objective prompts
#langsmith_eval.ls_client.delete_dataset(dataset_id="f288a17a-783b-4fd8-8605-0ff6ab8231fe")
dataset_name = "Description Questions - Performance (100 Sample)"
dataset_description = "Description prompts about performance"

datasets = langsmith_eval.ls_client.list_datasets()  # List all datasets
existing_dataset = next((ds for ds in datasets if ds.name == dataset_name), None)

if existing_dataset:
    dataset = existing_dataset
    print(f"Dataset '{dataset_name}' already exists. Loaded existing dataset.")
else:
    dataset = langsmith_eval.ls_client.create_dataset(
                    dataset_name=dataset_name,
                    description=dataset_description
                ) 

    # Specific question
    # Pick 20 random fund names
    list_names = metadata['fund_name']
    random_fund_names = random.sample(list_names, 100)
    for name in random_fund_names:
        for input_query in ["Describe the performance of " + name]:
            input_data = {"question": input_query, "top_k":1, "subject": {"text": "performance"}}
            retriever_chain = rag_chain.get_filtered_full_doc_retriever(input_data["question"])
            main_chain = rag_chain.description_perf_chain
            # Capture the expected retrieved result
            expected_result = capture_and_run_chain(input_data, retriever_chain, main_chain)
            print("Captured document retrieval")
            
            # Extract retrieved documents from expected run
            docs = expected_result["retrieved_docs"]
            print("Number of documents retrieved: ", len(docs))
            #assert len(docs) == 1, f"More than one document retrieved"
            #doc = docs[0]

            # The exposure prompt asks to use the exposure table and investment objective to answer the question
            # We provide the relevant metadata used for the CORRECT retrieval as reference output
            # We use the context to check for hallucination/ retrieval as reference output
            context_str = rag_chain.build_perf_context(docs, input_data["subject"]) # it's a string
            
            langsmith_eval.ls_client.create_example(
                inputs = {"question": input_query},
                outputs={"context": context_str},
                dataset_id = dataset.id
            )

#Run the evaluation on the dataset 
langsmith_eval.run_evaluation_on_dataset(dataset_name, rag_chain.execute_simple_llm, run_name = "simple_chain_gen_perf_100")
langsmith_eval.run_evaluation_on_dataset(dataset_name, rag_chain.execute_domain_specific_chain, run_name = "domain_chain_gen_perf_100")
langsmith_eval.run_evaluation_on_dataset(dataset_name, route_chain.execute_guided_full_chain, run_name = "route_chain_gen_perf_100")
langsmith_eval.run_evaluation_on_dataset(dataset_name, rag_chain.execute_agent_executor, run_name = "agent_chain_gen_perf_100")