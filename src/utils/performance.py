import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

@contextmanager
def timeit(label):
    """
    A context manager to measure the execution time of a block of code.

    Args:
        label (str): A label to identify the code block being timed.
    """
    start_time = time.time()
    try:
        yield
    finally:
        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.info(f"{label} took {elapsed_time:.4f} seconds")

# Example usage:
# with timeit("My long running task"):
#     # Code to be timed
#     ...
