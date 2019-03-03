import functools
import threading


class NotAbleToLock(Exception):
    pass


class ThreadSleep(object):
    __slots__ = ['lock', 'condition', ]

    def __init__(self):
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.condition.acquire()

    def __call__(self, seconds):
        self.condition.wait(seconds)


class RWSynchronization(object):
    '''
    Some objects can be viewed by many readers at the same time but only one
    writer can be allowed to modify it at a time, and all the readers usually
    need to wait for write to complete so there would not be dirty reads.

    RWSynchronization is a context manager that can use separetly created
    semaphor and a mutex to enable read/write.  If default, class local, mutex
    and semaphore are selected, then object is either a glofied resource,
    access limiter or not so spiffy mutex.
    '''
    def __init__(self, counting_semaphore=None, mutex_lock=None,
                 simultaneous_reads=1, blocking=True,
                 retries_until_locked=False, raise_this=NotAbleToLock,
                 write_lock=False):
        self.counting_semaphore = counting_semaphore or \
            threading.Semaphore(simultaneous_reads)
        self.mutex_lock = mutex_lock or threading.Lock()
        self.blocking = blocking
        self.retries_until_locked = retries_until_locked or 0
        self.simultaneous_reads = simultaneous_reads
        self.write_lock = write_lock
        self.to_raise = raise_this or NotAbleToLock
        self.thread_sleep = ThreadSleep()

    def _get_read_lock(self):
        retry = self.retries_until_locked or 1

        while retry:
            if self.mutex_lock.acquire(self.blocking):
                if self.counting_semaphore.acquire(self.blocking):
                    self.mutex_lock.release()
                    return True
                else:
                    self.mutex_lock.release()
            self.thread_sleep(0.0005)
            retry -= 1
        return False

    def _unlock_reader(self):
        self.counting_semaphore.release()

    def _get_write_lock(self):
        retry = self.retries_until_locked or 1

        while retry > 0:
            lockout_readers = self.simultaneous_reads
            if self.mutex_lock.acquire(self.blocking):
                while lockout_readers and retry:
                    if self.counting_semaphore.acquire(self.blocking):
                        lockout_readers -= 1
                    else:
                        while lockout_readers <= self.simultaneous_reads:
                            self.counting_semaphore.release()
                            lockout_readers += 1
                        self.thread_sleep(0.5)
                        retry -= 1
                if lockout_readers == 0:
                    return True
                if not retry:
                    break
            self.thread_sleep(0.0005)
            retry -= 1
        return False

    def _unlock_writer(self):
        unlock_readers = self.simultaneous_reads
        while unlock_readers:
            self.counting_semaphore.release()
            unlock_readers -= 1
        self.mutex_lock.release()

    def __enter__(self, ):
        locked = self._get_write_lock() if self.write_lock \
                      else self._get_read_lock()
        if not locked:
            raise self.to_raise("Not able to lock in Synchronization %s" %
                                "Read Lock" if not self.write_lock
                                else "Write Lock")

        return self

    def __exit__(self, *args):
        if self.write_lock:
            self._unlock_writer()
        else:
            self._unlock_reader()


class RWSynchronized(object):
    __slots__ = ['rwSynchronization', ]

    def __init__(self, counting_semaphore=None, mutex_lock=None,
                 simultaneous_reads=1, blocking=True,
                 retries_until_locked=False, raise_this=NotAbleToLock,
                 write_lock=False):
        self.rwSynchronization = RWSynchronization(
            counting_semaphore=counting_semaphore,
            mutex_lock=mutex_lock,
            simultaneous_reads=simultaneous_reads,
            blocking=blocking,
            retries_until_locked=retries_until_locked,
            raise_this=raise_this,
            write_lock=write_lock
        )

    def __call__(self, f,):
        def synchronized_wrapper(*args, **kwargs):
            self.rwSynchronization.__enter__()
            try:
                return f(*args, **kwargs)
            except Exception:
                raise
            finally:
                self.rwSynchronization.__exit__()

        functools.update_wrapper(synchronized_wrapper, f)
        return synchronized_wrapper


rwSynchronized = RWSynchronized


class Synchronization(object):
    def __init__(self, locks=None, rlock=True, blocking=True,
                 raise_this=NotAbleToLock, retries_until_locked=False):
        '''
        Here we need to descide what locks we are going to use.

        locks -- a list of lock to spin through, best to have the  right order
                that locks should be spun through.
        blocking -- always false if more than 1 lock in list otherwise true if
                not specified otherwise
        raise_this  -- exception that will be raised, default is NotAbleToLock
        retries_until_locked -- if False then defaul value for several locks is
                10.  Any retry is meant to be used by a different decorator.

        Exception -- NotAbleToLock is defualt exception raised
        '''

        if locks:
            self.locks = locks
        else:
            if rlock:
                self.locks = [threading.RLock(), ]
            else:
                self.locks = [threading.Lock(), ]

        def default_blocking():
            if len(locks) <= 1:
                return blocking
            else:
                return False

        self.blocking = default_blocking()

        def default_retries_until_locked():
            if len(locks) <= 1 or retries_until_locked > 0:
                return retries_until_locked
            return 10

        self.to_raise = raise_this or NotAbleToLock
        self.retries_until_locked = default_retries_until_locked()
        self.thread_sleep = ThreadSleep()

    def _get_locks(self):
        locked = []
        for lock in self.locks:
            if lock.acquire(self.blocking):
                locked.append(lock)
            else:
                for lock in locked:
                    lock.release()
                return False
        return True

    def _unlock(self):
        for lock in self.locks:
            lock.release()

    def __enter__(self, ):
        isLocked = self._get_locks()
        if not isLocked and not self.retries_until_locked:
            raise self.to_raise("Not able to acquire lock in synchronization.")

        retry = self.retries_until_locked or 0

        while retry and not isLocked:
            self.thread_sleep(0.0005)
            isLocked = self._get_locks()
            if isLocked:
                break
            retry -= 1

        if not isLocked:
            raise self.to_raise("Not able to acquire lock in synchronization.")

        return self

    def __exit__(self, *args):
        self._unlock()


class Synchronized(object):
    '''
    Making a decorator class for Synchronization, putting in
    self.Synchronization as the underlying mechanism.
    __slots__ below are just
    '''
    __slots__ = ['synchronization', ]

    def __init__(self, locks=None, rlock=True, blocking=True,
                 raise_this=NotAbleToLock, retries_until_locked=False):
        '''
        Here we need to descide what locks we are going to use.

        locks -- a list of lock to spin through, best to have the  right order
                 that locks should be spun through.
        blocking -- always false if more than 1 lock in list otherwise true if
                 not specified otherwise
        raise_this  -- exception that will be raised, default is NotAbleToLock
        retries_until_locked -- if False then defaul value for several locks is
                 10.  Any retry is meant to be used by a different decorator.

        Exception -- NotAbleToLock is raised
        '''
        self.synchronization = \
            Synchronization(locks=locks, rlock=rlock, blocking=blocking,
                            raise_this=raise_this,
                            retries_until_locked=retries_until_locked)

    def __call__(self, f):
        def wrapped_synched_test_func(*args, **kwargs):
            self.synchronization.__enter__()
            try:
                return f(*args, **kwargs)
            except Exception:
                raise
            finally:
                self.synchronization.__exit__()

        functools.update_wrapper(wrapped_synched_test_func, f)
        return wrapped_synched_test_func


synchronized = Synchronized  # decorators freuently used as lowercase names.

######################################################################
# It is best to put this one in a separate file.
######################################################################
import unittest


class UnitTest_RWSynchronization_MultiTread(unittest.TestCase):

    def setUp(self):
        '''
        Activities that will be started by thread,
            test_thread_run_target_reader
            test_thread_run_target_writer
        both have sleep times set via kwargs sleep_time passed in by
        threading.Thread(...) at startup.  This makes one thread come to a
        section when another has it locked.
        '''
        self.test_mutex_lock = threading.Lock()
        self.test_semaphore = threading.Semaphore()

        self.test_thread_activity1 = None
        self.test_thread_activity2 = None
        self.test_thread_activity3 = None

        def test_thread_run_target_writer(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity1:
                self.test_thread_activity1()

            print('%s done.' % self.thread_1.name)

        def test_thread_run_target_reader(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity2:
                self.test_thread_activity2(*args)

            print('%s done.' % self.thread_2.name)

        self.thread_1 = threading.Thread(name=repr(type(self))+' thread 1 W',
                                         target=test_thread_run_target_writer,
                                         kwargs={'sleep_time': 0.3})
        self.thread_2 = threading.Thread(name=repr(type(self))+' thread 2 R',
                                         target=test_thread_run_target_reader,
                                         kwargs={'sleep_time': 0.1},
                                         args=(2, ))
        self.thread_3 = threading.Thread(name=repr(type(self))+' thread 2 R',
                                         target=test_thread_run_target_reader,
                                         kwargs={'sleep_time': 0.31},
                                         args=(3, ))

    def setup_activitiesi_and_initial_state(self):
        self.expected_number_of_items = 2
        self.list_based_test_load = [0.14, 0.01, ]

        def test_thread_activity_writer():
            with RWSynchronization(mutex_lock=self.test_mutex_lock,
                                   counting_semaphore=self.test_semaphore,
                                   write_lock=True):
                thread_sleep = ThreadSleep()
                if self.expected_number_of_items != \
                        len(self.list_based_test_load):
                    self.assertFalse('Inconsistent thread work state')

                print("Thread_activity")
                sleep_interval = self.list_based_test_load.pop(0)
                thread_sleep(sleep_interval)
                self.expected_number_of_items = len(self.list_based_test_load)

                print("slept %d" % sleep_interval)

        def test_thread_activity_reader(start_order):
            with RWSynchronization(mutex_lock=self.test_mutex_lock,
                                   counting_semaphore=self.test_semaphore,
                                   write_lock=False):
                thread_sleep = ThreadSleep()
                if self.expected_number_of_items != \
                        len(self.list_based_test_load):
                    self.assertFalse('Inconsistent thread work state')

                print("Thread_activity")
                sleep_interval = 0.01
                if start_order == 2 and len(self.list_based_test_load) != 2:
                    self.assertFalse('Inconsistent thread work state')

                # came after the writer executed.
                if start_order == 3 and len(self.list_based_test_load) != 1:
                    self.assertFalse('Inconsistent thread_work state')
                thread_sleep(sleep_interval)

        self.test_thread_activity1 = test_thread_activity_writer
        self.test_thread_activity2 = test_thread_activity_reader
        self.test_thread_activity3 = test_thread_activity_reader

    def test_sychronized_activity(self):
        '''
        using list-based queue check work state, number of items = counter.
                Raise exception if state is inconsitent
         Writer will,
            1.  make inconsistent thread condition, pop one item off
            2.  sleep a randon interval that came from the list
            3.  fix inconsistent state.
         Reader will take an argument specifing it's expected start order,
            1.  If reader is expected to be at the synchronized section first,
                it will check that list has both items
            2.  If reader gets to the synchronized section last
                it checks that list only has one item
        '''
        self.setup_activitiesi_and_initial_state()

        try:
            self.thread_1.start()
            self.thread_2.start()
            self.thread_3.start()

            self.thread_1.join()
            self.thread_2.join()
            self.thread_3.join()
        except Exception as e:
            self.assertFalse(str(e) + ' ' + repr(e))
        else:
            self.assertTrue(True)


class UnitTest_RWSynchronization_OneThread(unittest.TestCase):

    def setUp(self):
        self.test_semaphore = threading.Semaphore(10)
        self.test_lock = threading.Lock()

    def test_rwSynchronized_OneThread_readlock(self):
        with RWSynchronization(counting_semaphore=self.test_semaphore,
                               mutex_lock=self.test_lock,
                               simultaneous_reads=1, blocking=True,
                               retries_until_locked=False,
                               raise_this=NotAbleToLock,
                               write_lock=False) as rw_synchronized:
            self.assertTrue(rw_synchronized)

    def test_rwSynchronized_OneThread_writelock(self):
        with RWSynchronization(counting_semaphore=self.test_semaphore,
                               mutex_lock=self.test_lock,
                               simultaneous_reads=1, blocking=True,
                               retries_until_locked=False,
                               raise_this=NotAbleToLock,
                               write_lock=True) as rw_synchronized:
            self.assertTrue(rw_synchronized)

    def test_rwSynchronized_OneThread_read_fail(self):
        self.test_lock.acquire()

        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=False,
                                   raise_this=NotAbleToLock,
                                   write_lock=False) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=1,
                                   raise_this=NotAbleToLock,
                                   write_lock=False) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=3,
                                   raise_this=NotAbleToLock,
                                   write_lock=False) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        self.test_lock.release()

    def test_rwSynchronized_OneThread_write_fail(self):
        self.test_lock.acquire()
        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=False,
                                   raise_this=NotAbleToLock,
                                   write_lock=True) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=1,
                                   raise_this=NotAbleToLock,
                                   write_lock=True) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            with RWSynchronization(counting_semaphore=self.test_semaphore,
                                   mutex_lock=self.test_lock,
                                   simultaneous_reads=1, blocking=False,
                                   retries_until_locked=3,
                                   raise_this=NotAbleToLock,
                                   write_lock=True) as rw_synchronized:
                self.assertFalse("Should not have gotten locked, %s"
                                 % rw_synchronized)
            self.assertTrue(e)

        self.test_lock.release()


class UnitTest_RWSynchronized_MultiTread(unittest.TestCase):

    def setUp(self):
        '''
        Activities that will be started by thread,
            test_thread_run_target_reader
            test_thread_run_target_writer
        both have sleep times set via kwargs sleep_time passed in by
        threading.Thread(...) at startup.  This makes one thread come to a
        section when another has it locked.
        '''
        self.test_mutex_lock = threading.Lock()
        self.test_semaphore = threading.Semaphore()

        self.test_thread_activity1 = None
        self.test_thread_activity2 = None
        self.test_thread_activity3 = None

        def test_thread_run_target_writer(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity1:
                self.test_thread_activity1()

            print('%s done.' % self.thread_1.name)

        def test_thread_run_target_reader(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity2:
                self.test_thread_activity2(*args)

            print('%s done.' % self.thread_2.name)

        self.thread_1 = threading.Thread(name=repr(type(self))+' thread 1 W',
                                         target=test_thread_run_target_writer,
                                         kwargs={'sleep_time': 0.3})
        self.thread_2 = threading.Thread(name=repr(type(self))+' thread 2 R',
                                         target=test_thread_run_target_reader,
                                         kwargs={'sleep_time': 0.1},
                                         args=(2, ))
        self.thread_3 = threading.Thread(name=repr(type(self))+' thread 2 R',
                                         target=test_thread_run_target_reader,
                                         kwargs={'sleep_time': 0.31},
                                         args=(3, ))

    def setup_activitiesi_and_initial_state(self):
        self.expected_number_of_items = 2
        self.list_based_test_load = [0.14, 0.01, ]

        @rwSynchronized(mutex_lock=self.test_mutex_lock,
                        counting_semaphore=self.test_semaphore,
                        write_lock=True)
        def test_thread_activity_writer():
            thread_sleep = ThreadSleep()
            if self.expected_number_of_items != \
                    len(self.list_based_test_load):
                self.assertFalse('Inconsistent thread work state')

            print("Thread_activity")
            sleep_interval = self.list_based_test_load.pop(0)
            thread_sleep(sleep_interval)
            self.expected_number_of_items = len(self.list_based_test_load)

            print("slept %d" % sleep_interval)

        @rwSynchronized(mutex_lock=self.test_mutex_lock,
                        counting_semaphore=self.test_semaphore,
                        write_lock=False)
        def test_thread_activity_reader(start_order):
            thread_sleep = ThreadSleep()
            if self.expected_number_of_items != \
                    len(self.list_based_test_load):
                self.assertFalse('Inconsistent thread work state')

            print("Thread_activity")
            sleep_interval = 0.01
            if start_order == 2 and len(self.list_based_test_load) != 2:
                self.assertFalse('Inconsistent thread work state')

            # came after the writer executed.
            if start_order == 3 and len(self.list_based_test_load) != 1:
                self.assertFalse('Inconsistent thread_work state')
            thread_sleep(sleep_interval)

        self.test_thread_activity1 = test_thread_activity_writer
        self.test_thread_activity2 = test_thread_activity_reader
        self.test_thread_activity3 = test_thread_activity_reader

    def test_sychronized_activity(self):
        '''
        using list-based queue check work state, number of items = counter.
                Raise exception if state is inconsitent
         Writer will,
            1.  make inconsistent thread condition, pop one item off
            2.  sleep a randon interval that came from the list
            3.  fix inconsistent state.
         Reader will take an argument specifing it's expected start order,
            1.  If reader is expected to be at the synchronized section first,
                it will check that list has both items
            2.  If reader gets to the synchronized section last
                it checks that list only has one item
        '''
        self.setup_activitiesi_and_initial_state()

        try:
            self.thread_1.start()
            self.thread_2.start()
            self.thread_3.start()

            self.thread_1.join()
            self.thread_2.join()
            self.thread_3.join()
        except Exception as e:
            self.assertFalse(str(e) + ' ' + repr(e))
        else:
            self.assertTrue(True)


class UnitTest_RWSynchronized_OneThread(unittest.TestCase):

    def setUp(self):
        self.test_semaphore = threading.Semaphore(10)
        self.test_lock = threading.Lock()

    def test_rwSynchronized_OneThread_readlock(self):
        @rwSynchronized(counting_semaphore=self.test_semaphore,
                        mutex_lock=self.test_lock,
                        simultaneous_reads=1, blocking=True,
                        retries_until_locked=False,
                        raise_this=NotAbleToLock,
                        write_lock=False)
        def test_synch_func():
            self.assertTrue("function passed")
        test_synch_func()

    def test_rwSynchronized_OneThread_writelock(self):
        @rwSynchronized(counting_semaphore=self.test_semaphore,
                        mutex_lock=self.test_lock,
                        simultaneous_reads=1, blocking=True,
                        retries_until_locked=False,
                        raise_this=NotAbleToLock,
                        write_lock=True)
        def test_synch_func():
            self.assertTrue("function passed")
        test_synch_func()

    def test_rwSynchronized_OneThread_read_fail(self):
        self.test_lock.acquire()

        with self.assertRaises(NotAbleToLock) as e:
            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=False,
                            raise_this=NotAbleToLock,
                            write_lock=False)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:

            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=1,
                            raise_this=NotAbleToLock,
                            write_lock=False)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=3,
                            raise_this=NotAbleToLock,
                            write_lock=False)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        self.test_lock.release()

    def test_rwSynchronized_OneThread_write_fail(self):
        self.test_lock.acquire()
        with self.assertRaises(NotAbleToLock) as e:
            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=False,
                            raise_this=NotAbleToLock,
                            write_lock=True)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=1,
                            raise_this=NotAbleToLock,
                            write_lock=True)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        with self.assertRaises(NotAbleToLock) as e:
            @rwSynchronized(counting_semaphore=self.test_semaphore,
                            mutex_lock=self.test_lock,
                            simultaneous_reads=1, blocking=False,
                            retries_until_locked=3,
                            raise_this=NotAbleToLock,
                            write_lock=True)
            def test_synch_func():
                self.assertFalse("Should not have gotten locked")
            test_synch_func()
            self.assertTrue(e)

        self.test_lock.release()


class UnitTest_Synchronization_OneThread(unittest.TestCase):

    def setUp(self):
        self.test_rlock = threading.RLock()
        self.test_lock = threading.Lock()
        self.locks = [threading.Lock(), threading.Lock(), threading.Lock(), ]

    def test_no_spawned_thread_run(self):
        with Synchronization(self.locks):
            self.assertEqual(1, 1)

    def test_no_spawned_thread_run_prelocked(self):
        self.locks[0].acquire()
        with self.assertRaises(NotAbleToLock) as cm:
            with Synchronization(self.locks):
                self.assertEqual(0, -1)
        self.assertTrue(cm.exception)

        with self.assertRaises(NotAbleToLock) as cm:
            with Synchronization(self.locks,
                                 blocking=False,
                                 retries_until_locked=10):
                self.assertEqual(0, -1)
        self.assertTrue(cm.exception)


class UnitTest_Synchronized_OneThread(unittest.TestCase):
    '''
    Tests the decorator version of synchronization.
    '''

    def setUp(self):
        self.test_rlock = threading.RLock()
        self.test_lock = threading.Lock()
        self.locks = [threading.Lock(), threading.Lock(), threading.Lock(), ]

    def test_no_spawned_thread_run(self):
        @synchronized(self.locks)
        def synchronized_test_func(*args, **kwargs):
            pass
        synchronized_test_func()
        self.assertEqual(1, 1)

    def test_no_spawned_thread_run_prelocked(self):
        self.locks[0].acquire()
        with self.assertRaises(NotAbleToLock) as cm:
            @synchronized(self.locks, blocking=False)
            def synchronized_test_func(*args, **kwargs):
                self.assertEqual(0, -1)
            synchronized_test_func()

        self.assertTrue(cm.exception)

        with self.assertRaises(NotAbleToLock) as cm:
            @synchronized(self.locks, blocking=False, retries_until_locked=10)
            def synchronized_test_func(*args, **kwargs):
                self.assertEqual(0, -1)
            synchronized_test_func()

        self.assertTrue(cm.exception)


class UnitTest_Synchronization_MultiThread(unittest.TestCase):

    def setUp(self):
        '''
        Activities that will be started by thread,
            test_thread_run_target_1
            test_thread_run_target_2
        both have sleep times set via kwargs sleep_time passed in by
        threading.Thread(...) at startup.  This makes one thread come to a
        section when another has it locked.
        '''
        self.test_rlock = threading.RLock()
        self.test_lock = threading.Lock()
        self.locks = [threading.Lock(), threading.Lock(), threading.Lock(), ]

        self.test_thread_activity1 = None
        self.test_thread_activity2 = None

        def test_thread_run_target_1(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity1:
                self.test_thread_activity1()

            print('%s done.' % self.thread_1.name)

        def test_thread_run_target_2(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity2:
                self.test_thread_activity2()

            print('%s done.' % self.thread_2.name)

        self.thread_1 = threading.Thread(name=repr(type(self))+' thread 1',
                                         target=test_thread_run_target_1,
                                         kwargs={'sleep_time': 0.3})
        self.thread_2 = threading.Thread(name=repr(type(self))+' thread 2',
                                         target=test_thread_run_target_2,
                                         kwargs={'sleep_time': 0.1})

    def test_sychronized_activity(self):
        '''
        1.  using list-based queue check work state, number of items = counter.
                Raise exception if state is inconsitent
        2.  make inconsistent thread condition, pop one item off
        3.  sleep a randon interval
        4.  fix inconsistent state.
        '''
        self.expected_number_of_items = 2
        self.list_based_test_load = [0.14, 0.01, ]

        def test_thread_activity():
            with Synchronization([self.test_lock]):
                thread_sleep = ThreadSleep()
                if self.expected_number_of_items != \
                        len(self.list_based_test_load):
                    self.assertFalse('Inconsistent thread work state')

                print("Thread_activity")
                sleep_interval = self.list_based_test_load.pop(0)
                thread_sleep(sleep_interval)
                self.expected_number_of_items = len(self.list_based_test_load)

                print("slept %d" % sleep_interval)

        self.test_thread_activity1 = test_thread_activity
        self.test_thread_activity2 = test_thread_activity

        try:
            self.thread_1.start()
            self.thread_2.start()

            self.thread_1.join()
            self.thread_2.join()
        except Exception as e:
            self.assertFalse(str(e) + ' ' + repr(e))
        else:
            self.assertTrue(True)


class UnitTest_Synchronized_MultiThread(unittest.TestCase):

    def setUp(self):
        self.test_rlock = threading.RLock()
        self.test_lock = threading.Lock()
        self.locks = [threading.Lock(), threading.Lock(), threading.Lock(), ]

        self.test_thread_activity1 = None
        self.test_thread_activity2 = None

        def test_thread_run_target_1(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity1:
                self.test_thread_activity1()

            print('%s done.' % self.thread_1.name)

        def test_thread_run_target_2(*args, **kwargs):
            thread_sleep = ThreadSleep()
            thread_sleep(kwargs.get('sleep_time'))
            if self.test_thread_activity2:
                self.test_thread_activity2()

            print('%s done.' % self.thread_2.name)

        self.thread_1 = threading.Thread(name=repr(type(self))+' thread 1',
                                         target=test_thread_run_target_1,
                                         kwargs={'sleep_time': 0.3})
        self.thread_2 = threading.Thread(name=repr(type(self))+' thread 2',
                                         target=test_thread_run_target_2,
                                         kwargs={'sleep_time': 0.1})

    def test_sychronized_activity(self):
        '''
        1.  using list-based queue check work state, number of items = counter.
                Raise exception if state is inconsitent
        2.  make inconsistent thread condition, pop one item off
        3.  sleep a randon interval
        4.  fix inconsistent state.
        '''
        self.expected_number_of_items = 2
        self.list_based_test_load = [0.3, 0.4, ]

        @synchronized([self.test_lock])
        def test_thread_activity():
            thread_sleep = ThreadSleep()
            if self.expected_number_of_items != len(self.list_based_test_load):
                raise Exception('Inconsistent thread work stated')
            sleep_interval = self.list_based_test_load.pop(0)

            print("Thread_activity")
            thread_sleep(sleep_interval)

            self.expected_number_of_items = len(self.list_based_test_load)

            print("slept: ", sleep_interval)

        self.test_thread_activity1 = test_thread_activity
        self.test_thread_activity2 = test_thread_activity

        try:
            self.thread_1.start()
            self.thread_2.start()

            self.thread_1.join()
            self.thread_2.join()
        except Exception as e:
            self.assertFalse(str(e) + ' ' + repr(e))


if __name__ == '__main__':
    unittest.main()
