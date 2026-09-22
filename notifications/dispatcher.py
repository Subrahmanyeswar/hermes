from notifications.channels.email import EmailChannel
from notifications.channels.sms import SMSChannel
from notifications.queue import Queue

class NotificationDispatcher:
    def __init__(self):
        self.queue = Queue()

    def dispatch(self, notification):
        # notification should have 'type' and 'content'
        if notification['type'] == 'email':
            self.queue.add_email(notification)
        elif notification['type'] == 'sms':
            self.queue.add_sms(notification)
        else:
            raise ValueError("Unknown notification type")