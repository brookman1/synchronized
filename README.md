# synchronized 0.000000001
This code is an exhibit.  You may clone/copy this code and use it as your idea, as long as I can keep working on/extending it as my idea.  Next version may not support current usage.

Python synchronized utilities, enable to make synchronized functions and contexts.  RW Locking.  Intention is to get code like this to work consistently and simultaneously:

<pre>
import threading
from Queue import Queue

work_queue = Queue()
def thread_run(*args, **args):
    a_lock = threading.Lock()
    a_list = [1, 2, 3, 4, 'a', 'b', 'c', {'stuff', '<a href="http://not_working_url._z_z_">here</a>'}]
    
    @synchronized(locks = [threading.Lock(), ]):
    def my_non_automic_list_access_in_thread_or_process(*args, **kwargs):
        some_list = args[0]
        idx = list.find(args[1])
        list.pop(idx)
    
    index = work_queue.get()
    my_non_automic_list_access_in_thread_or_process(a_list, index)
    
    
</pre>    

See testcases included for basic usage.

## Synchronized functions
    Main TODO : 
                1. Make tracking accessors of what thread / process locked, and on what line.
                2. Testcases via multiprocess module.

## In the works
### logger emitter that can,
    a. do pprinting and do abbreviation of start ... end of string / list / dict / tuple data.
    b. can print out debug info for past iterations if critical / error was logged or if exception is raised.
    c. can put detailed locks into a wrapping buffer that can be attached to with a watcher, while saving
       other levels [INFO / WARN / ERROR / CRITICAL] into a log output.
