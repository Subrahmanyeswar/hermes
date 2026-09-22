import sys

def main():
    try:
        # If an argument is provided, echo it, otherwise echo 'hello'
        if len(sys.argv) > 1:
            print(sys.argv[1])
        else:
            print('hello')
    except Exception as e:
        print(f'An error occurred: {e}', file=sys.stderr)

if __name__ == '__main__':
    main()
