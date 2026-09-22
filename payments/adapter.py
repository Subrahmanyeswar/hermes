import abc
import logging

class PaymentAdapter(metaclass=abc.ABCMeta):
    """Interface for payment providers."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @abc.abstractmethod
    def process_payment(self, amount, currency, **kwargs):
        """Process a payment."""
        pass

    @abc.abstractmethod
    def get_status(self):
        """Get the status of the payment."""
        pass

    def log_message(self, message):
        """Log a message."""
        self.logger.info(message)