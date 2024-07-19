"""Script to evaluate QA Correctness Guard on benchmark dataset.
The 2.0 version of the large-scale dataset Stanford Question Answering Dataset (SQuAD 2.0) allows
researchers to design AI models for reading comprehension tasks under challenging constraints.
https://web.stanford.edu/class/archive/cs/cs224n/cs224n.1194/reports/default/15785042.pdf

INFO:root:Guard Results
INFO:root:              precision    recall  f1-score   support

       False       1.00      0.94      0.97        50
        True       0.94      1.00      0.97        50

    accuracy                           0.97       100
   macro avg       0.97      0.97      0.97       100
weighted avg       0.97      0.97      0.97       100

INFO:root:Latency
INFO:root:count    100.000000
mean       1.845307
std        0.867450
min        0.982674
25%        1.354958
50%        1.606060
75%        1.928065
max        6.342991
Name: guard_latency, dtype: float64
"""
import os
import time
from getpass import getpass
from typing import List, Tuple
import logging
import random

import openai
import pandas as pd
from sklearn.metrics import classification_report

from guardrails import Guard
from main import QACorrectnessPrompt, LlmRagEvaluator
from phoenix.evals import download_benchmark_dataset
from sklearn.utils import shuffle

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)

random.seed(119)


MODEL = "gpt-4o-mini"
N_EVAL_SAMPLE_SIZE = 100


def evaluate_guard_on_dataset(test_dataset: pd.DataFrame, guard: Guard) -> Tuple[List[float], List[bool]]:
    """Evaluate guard on benchmark dataset.

    :param test_dataset: Dataframe of test examples.
    :param guard: Guard we want to evaluate.

    :return: Tuple where the first lists contains latency, and the second list contains a boolean indicating whether the guard passed.
    """
    latency_measurements = []
    guard_passed = []
    for _, rag_example in test_dataset.iterrows():
        start_time = time.perf_counter()
        response = guard(
            llm_api=openai.chat.completions.create,
            prompt=rag_example["question"],
            model=MODEL,
            max_tokens=1024,
            temperature=0.5,
            metadata={
                "user_message": rag_example["question"],
                "context": rag_example["context"],
                "llm_response": rag_example["sampled_answer"],
            }
        )
        latency_measurements.append(time.perf_counter() - start_time)
        logging.info(response)
        guard_passed.append(response.validation_passed)
    return latency_measurements, guard_passed


if __name__ == "__main__":
    if not (openai_api_key := os.getenv("OPENAI_API_KEY")):
        openai_api_key = getpass("🔑 Enter your OpenAI API key: ")
    openai.api_key = openai_api_key
    os.environ["OPENAI_API_KEY"] = openai_api_key
    
    # Columns: Index(['id', 'title', 'context', 'question', 'answers', 'correct_answer', 'wrong_answer', 'sampled_answer', 'answer_true']
    test_dataset = df = download_benchmark_dataset(
        task="qa-classification",
        dataset_name="qa_generated_dataset")
    test_dataset = shuffle(test_dataset)
    test_dataset = test_dataset[:N_EVAL_SAMPLE_SIZE]
    
    guard = Guard.from_string(
        validators=[
            LlmRagEvaluator(
                eval_llm_prompt_generator=QACorrectnessPrompt(prompt_name="qa_correctness_judge_llm"),
                llm_evaluator_fail_response="incorrect",
                llm_evaluator_pass_response="correct",
                llm_callable=MODEL,
                on_fail="noop",
                on="prompt")
        ],
    )
    
    latency_measurements, guard_passed = evaluate_guard_on_dataset(test_dataset=test_dataset, guard=guard)
    test_dataset["guard_passed"] = guard_passed
    test_dataset["guard_latency"] = latency_measurements
    
    logging.info("Guard Results")
    # Calculate precision, recall and f1-score for when the Guard fails (e.g. flags an incorrect answer)
    logging.info(classification_report(~test_dataset["answer_true"], ~test_dataset["guard_passed"]))
    
    logging.info("Latency")
    logging.info(test_dataset["guard_latency"].describe())