class Logger:
    """A simple Logger class to avoid shadowing built-in logging."""

    def __init__(self, name):
        self.name = name

    def debug(self, message):
        self.log(message, 'debug')

    def info(self, message):
        self.log(message, 'info')

    def warning(self, message):
        self.log(message, 'warning')

    def error(self, message):
        self.log(message, 'error')

    def log(self, message, level='info'):
        levels = {'debug': 10, 'info': 20, 'warning': 30, 'error': 40}
        level = levels.get(level.lower(), 20)
        print(f"[{self.name}] [{level}] {message}")