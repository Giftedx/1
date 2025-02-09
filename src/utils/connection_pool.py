import asyncio
import logging

logger = logging.getLogger(__name__)

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
            logger.debug(f"Connection established to {host}:{port}")
            return reader, writer
        except Exception as e:
            logger.error(f"Error creating connection to {host}:{port}: {e}")
            return None, None

    async def fill_pool():
        """Fills the connection pool with initial connections."""
        for _ in range(min_connections):
            reader, writer = await connection_factory()
            if reader and writer:
                await connection_queue.put((reader, writer))
            else:
                logger.warning("Failed to create initial connection, pool may be smaller than expected.")

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
    try:
        return await connection_queue.get()
    except Exception as e:
        logger.error(f"Error getting connection from pool: {e}")
        return None, None

async def release_connection(connection_queue, reader, writer):
    """
    Releases a connection back to the connection pool.

    Args:
        connection_queue (asyncio.Queue): The connection pool queue.
        reader: The reader object.
        writer: The writer object.
    """
    try:
        await connection_queue.put((reader, writer))
        logger.debug("Connection released back to pool.")
    except Exception as e:
        logger.error(f"Error releasing connection to pool: {e}")
        await close_connection(reader, writer)  # Close if release fails

async def close_connection(reader, writer):
    """
    Closes a connection.

    Args:
        reader: The reader object.
        writer: The writer object.
    """
    try:
        writer.close()
        await writer.wait_closed()
        logger.debug("Connection closed.")
    except Exception as e:
        logger.error(f"Error closing connection: {e}")

# Example usage:
# connection_pool = await create_connection_pool("localhost", 8080)
# reader, writer = await get_connection(connection_pool)
# # Use the connection
# await release_connection(connection_pool, reader, writer)
