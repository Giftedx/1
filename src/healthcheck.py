import http.client
import sys

def check_health(host='localhost', port=8080, path='/health'):
    try:
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("GET", path)
        response = conn.getresponse()
        if response.status == 200:
            print("Health check passed")
            sys.exit(0)
        else:
            print(f"Health check failed with status code: {response.status}")
            sys.exit(1)
    except Exception as e:
        print(f"Health check failed with exception: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    check_health()
