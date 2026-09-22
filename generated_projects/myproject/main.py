import sys

def greet(name):
    return f"Hello, {name}!"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(greet(sys.argv[1]))
    else:
        print("Usage: python main.py [name]")