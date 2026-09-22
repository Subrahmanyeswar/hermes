def log_audit(event):
    """Log audit events."""
    with open('audit.log', 'a') as f:
        f.write(f"{event}\n")