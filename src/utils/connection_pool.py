import asyncio

async def create_connection_pool(host, port, min_connections=1, max_connections=10):
    """
    Creates an asyncio connection pool.

    Args:
        host (str): The host address.
        port (int): The port number.
        min_connections (int): The minimum number of connections in the pool.
        max_connections (int): The maximum number of connections in the pool.

    Returns:
        asyncio.Queue: A queue representing the connection pool.
    """
    connection_queue = asyncio.Queue(maxsize=max_connections)

    async def connection_factory():
        """Factory function to create a new connection."""
        try:
            reader, writer = await asyncio.open_connection(host, port)
            return reader, writer
        except Exception as e:
            print(f"Error creating connection: {e}")
            return None, None

    async def fill_pool():
        """Fills the connection pool with initial connections."""
        for _ in range(min_connections):
            reader, writer = await connection_factory()
            if reader and writer:
                await connection_queue.put((reader, writer))

    await fill_pool()
    return connection_queue

async def get_connection(connection_queue):
    """
    Gets a connection from the connection pool.

    Args:
        connection_queue (asyncio.Queue): The connection pool queue.

    Returns:
        tuple: A tuple containing the reader and writer objects.
    """
    return await connection_queue.get()

async def release_connection(connection_queue, reader, writer):
    """
    Releases a connection back to the connection pool.

    Args:
        connection_queue (asyncio.Queue): The connection pool queue.
        reader: The reader object.
        writer: The writer object.
    """
    await connection_queue.put((reader, writer))

async def close_connection(reader, writer):
    """
    Closes a connection.

    Args:
        reader: The reader object.
        writer: The writer object.
    """
    writer.close()
    await writer.wait_closed()

# Example usage:
# connection_pool = await create_connection_pool("localhost", 8080)
# reader, writer = await get_connection(connection_pool)
# # Use the connection
# await release_connection(connection_pool, reader, writer)
