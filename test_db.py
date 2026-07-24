import asyncio
import db

async def test():
    mems = await db.get_all_admin_memories()
    print("Memories count:", len(mems))
    rules = await db.get_style_rules()
    print("Rules count:", len(rules))

asyncio.run(test())
