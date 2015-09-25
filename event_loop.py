# An event loop
def run_until_complete(coro):
    current_tasks = coro
    while True:
        next_tasks = []
        for task in current_tasks:
            # Running asyncio.ensure_future(coro) in a task causes
            # a task to be created and appended to `next_tasks`.
            task.run()
        current_tasks = next_tasks
