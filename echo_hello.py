import sys


def echo_hello():
    """Echoes 'hello' to the console."""
    try:
        print("hello")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    echo_hello()