import logging

def test_logging_setup():
    logger = logging.getLogger('test_logger')
    logger.setLevel(logging.DEBUG)
    
    assert logger.level == logging.DEBUG
    assert isinstance(logger.handlers, list)