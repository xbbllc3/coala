import multiprocessing
import queue
import os
import platform
import subprocess

from coalib.collecting.Collectors import collect_files
from coalib.collecting import Dependencies
from coalib.misc.StringConverter import StringConverter
from coalib.output.printers import LOG_LEVEL
from coalib.processes.BearRunning import run
from coalib.processes.CONTROL_ELEMENT import CONTROL_ELEMENT
from coalib.results.Result import Result
from coalib.results.RESULT_SEVERITY import RESULT_SEVERITY
from coalib.results.SourceRange import SourceRange
from coalib.settings.Setting import path_list
from coalib.processes.LogPrinterThread import LogPrinterThread


def get_cpu_count():
    try:
        return multiprocessing.cpu_count()
    # cpu_count is not implemented for some CPU architectures/OSes
    except NotImplementedError:  # pragma: no cover
        return 2


def fill_queue(queue_fill, any_list):
    """
    Takes element from a list and populates a queue with those elements.

    :param queue_fill: The queue to be filled.
    :param any_list:   List containing the elements.
    """
    for elem in any_list:
        queue_fill.put(elem)


def get_running_processes(processes):
    return sum((1 if process.is_alive() else 0) for process in processes)


def create_process_group(command_array, **kwargs):
    if platform.system() == "Windows":  # pragma: no cover
        proc = subprocess.Popen(
            command_array,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            **kwargs)
    else:
        proc = subprocess.Popen(command_array,
                                preexec_fn=os.setsid,
                                **kwargs)
    return proc


def print_result(results,
                 file_dict,
                 retval,
                 print_results,
                 section,
                 log_printer,
                 file_diff_dict,
                 ignore_ranges):
    """
    Takes the results produced by each bear and gives them to the print_results
    method to present to the user.

    :param results:        A list of results.
    :param file_dict:      A dictionary containing the name of files and its
                           contents.
    :param retval:         It is True if no results were yielded ever before.
                           If it is False this function will return False no
                           matter what happens. Else it depends on if this
                           invocation yields results.
    :param print_results:  A function that prints all given results appropriate
                           to the output medium.
    :param file_diff_dict: A dictionary that contains filenames as keys and
                           diff objects as values.
    :param ignore_ranges:  A list of SourceRanges. Results that affect code in
                           any of those ranges will be ignored.
    :return:               Returns False if any results were yielded. Else
                           True.
    """
    min_severity_str = str(section.get('min_severity', 'INFO')).upper()
    min_severity = RESULT_SEVERITY.str_dict.get(min_severity_str, 'INFO')
    results = list(filter(lambda result:
                              type(result) is Result and
                              result.severity >= min_severity and
                              not result.to_ignore(ignore_ranges),
                          results))
    print_results(log_printer, section, results, file_dict, file_diff_dict)
    return retval or len(results) > 0


def get_file_dict(filename_list, log_printer):
    """
    Reads all files into a dictionary.

    :param filename_list: List of names of paths to files to get contents of.
    :param log_printer:   The logger which logs errors.
    :return:              Reads the content of each file into a dictionary
                          with filenames as keys.
    """
    file_dict = {}
    for filename in filename_list:
        try:
            with open(filename, "r", encoding="utf-8") as _file:
                file_dict[filename] = _file.readlines()
        except UnicodeDecodeError:
            log_printer.warn("Failed to read file '{}'. It seems to contain "
                             "non-unicode characters. Leaving it "
                             "out.".format(filename))
        except Exception as exception:  # pragma: no cover
            log_printer.log_exception("Failed to read file '{}' because of "
                                      "an unknown error. Leaving it "
                                      "out.".format(filename),
                                      exception,
                                      log_level=LOG_LEVEL.WARNING)

    return file_dict


def instantiate_bears(section,
                      local_bear_list,
                      global_bear_list,
                      file_dict,
                      message_queue):
    """
    Instantiates each bear with the arguments it needs.

    :param section:          The section the bears belong to.
    :param local_bear_list:  List of local bears to instantiate.
    :param global_bear_list: List of global bears to instantiate.
    :param file_dict:        Dictionary containing filenames and their
                             contents.
    :param message_queue:    Queue responsible to maintain the messages
                             delivered by the bears.
    """
    for i in range(len(local_bear_list)):
        try:
            local_bear_list[i] = local_bear_list[i](section,
                                                    message_queue,
                                                    timeout=0.1)
        except RuntimeError:
            # If requirements of a bear are not fulfilled this is not a reason
            # to stop instantiating bears.
            pass

    for i in range(len(global_bear_list)):
        try:
            global_bear_list[i] = global_bear_list[i](file_dict,
                                                      section,
                                                      message_queue,
                                                      timeout=0.1)
        except RuntimeError:
            pass


def instantiate_processes(section,
                          local_bear_list,
                          global_bear_list,
                          job_count,
                          log_printer):
    """
    Instantiate the number of processes that will run bears which will be
    responsible for running bears in a multiprocessing environment.

    :param section:          The section the bears belong to.
    :param local_bear_list:  List of local bears belonging to the section.
    :param global_bear_list: List of global bears belonging to the section.
    :param job_count:        Max number of processes to create.
    :param log_printer:      The log printer to warn to.
    :return:                 A tuple containing a list of processes,
                             and the arguments passed to each process which are
                             the same for each object.
    """
    filename_list = collect_files(path_list(section.get('files', "")),
                                  path_list(section.get('ignore', "")))
    file_dict = get_file_dict(filename_list, log_printer)

    manager = multiprocessing.Manager()
    global_bear_queue = multiprocessing.Queue()
    filename_queue = multiprocessing.Queue()
    local_result_dict = manager.dict()
    global_result_dict = manager.dict()
    message_queue = multiprocessing.Queue()
    control_queue = multiprocessing.Queue()

    bear_runner_args = {"file_name_queue": filename_queue,
                        "local_bear_list": local_bear_list,
                        "global_bear_list": global_bear_list,
                        "global_bear_queue": global_bear_queue,
                        "file_dict": file_dict,
                        "local_result_dict": local_result_dict,
                        "global_result_dict": global_result_dict,
                        "message_queue": message_queue,
                        "control_queue": control_queue,
                        "timeout": 0.1}

    instantiate_bears(section,
                      local_bear_list,
                      global_bear_list,
                      file_dict,
                      message_queue)
    fill_queue(filename_queue, file_dict.keys())
    fill_queue(global_bear_queue, range(len(global_bear_list)))

    return ([multiprocessing.Process(target=run, kwargs=bear_runner_args)
             for i in range(job_count)],
            bear_runner_args)


def get_ignore_scope(line, keyword):
    """
    Retrieves the bears that are to be ignored defined in the given line.
    :param line:    The line containing the ignore declaration.
    :param keyword: The keyword that was found. Everything after the rightmost
                    occurrence of it will be considered for the scope.
    :return:        A list of lower cased bearnames or an empty list (-> "all")
    """
    toignore = line[line.rfind(keyword) + len(keyword):]
    if toignore.startswith("all"):
        return []
    else:
        return list(StringConverter(toignore, list_delimiters=', '))


def yield_ignore_ranges(file_dict):
    """
    Yields tuples of affected bears and a SourceRange that shall be ignored for
    those.

    :param file_dict: The file dictionary.
    """
    for filename, file in file_dict.items():
        start = None
        bears = []
        for line_number, line in enumerate(file, start=1):
            line = line.lower()
            if "start ignoring " in line:
                start = line_number
                bears = get_ignore_scope(line, "start ignoring ")
            elif "stop ignoring" in line:
                if start:
                    yield (bears,
                           SourceRange.from_values(filename,
                                                   start,
                                                   end_line=line_number))
            elif "ignore " in line:
                yield (get_ignore_scope(line, "ignore "),
                       SourceRange.from_values(filename,
                                               line_number,
                                               end_line=line_number+1))


def process_queues(processes,
                   control_queue,
                   local_result_dict,
                   global_result_dict,
                   file_dict,
                   print_results,
                   section,
                   log_printer):
    """
    Iterate the control queue and send the results recieved to the print_result
    method so that they can be presented to the user.

    :param processes:          List of processes which can be used to run
                               Bears.
    :param control_queue:      Containing control elements that indicate
                               whether there is a result available and which
                               bear it belongs to.
    :param local_result_dict:  Dictionary containing results respective to
                               local bears. It is modified by the processes
                               i.e. results are added to it by multiple
                               processes.
    :param global_result_dict: Dictionary containing results respective to
                               global bears. It is modified by the processes
                               i.e. results are added to it by multiple
                               processes.
    :param file_dict:          Dictionary containing file contents with
                               filename as keys.
    :param print_results:      Prints all given results appropriate to the
                               output medium.
    :return:                   Return True if all bears execute succesfully and
                               Results were delivered to the user. Else False.
    """
    file_diff_dict = {}
    running_processes = get_running_processes(processes)
    retval = False
    # Number of processes working on local bears
    local_processes = len(processes)
    global_result_buffer = []
    ignore_ranges = list(yield_ignore_ranges(file_dict))

    # One process is the logger thread
    while local_processes > 1 and running_processes > 1:
        try:
            control_elem, index = control_queue.get(timeout=0.1)

            if control_elem == CONTROL_ELEMENT.LOCAL_FINISHED:
                local_processes -= 1
            elif control_elem == CONTROL_ELEMENT.LOCAL:
                assert local_processes != 0
                retval = print_result(local_result_dict[index],
                                      file_dict,
                                      retval,
                                      print_results,
                                      section,
                                      log_printer,
                                      file_diff_dict,
                                      ignore_ranges)
            elif control_elem == CONTROL_ELEMENT.GLOBAL:
                global_result_buffer.append(index)
        except queue.Empty:
            running_processes = get_running_processes(processes)

    # Flush global result buffer
    for elem in global_result_buffer:
        retval = print_result(global_result_dict[elem],
                              file_dict,
                              retval,
                              print_results,
                              section,
                              log_printer,
                              file_diff_dict,
                              ignore_ranges)

    running_processes = get_running_processes(processes)
    # One process is the logger thread
    while running_processes > 1:
        try:
            control_elem, index = control_queue.get(timeout=0.1)

            if control_elem == CONTROL_ELEMENT.GLOBAL:
                retval = print_result(global_result_dict[index],
                                      file_dict,
                                      retval,
                                      print_results,
                                      section,
                                      log_printer,
                                      file_diff_dict,
                                      ignore_ranges)
            else:
                assert control_elem == CONTROL_ELEMENT.GLOBAL_FINISHED
                running_processes = get_running_processes(processes)

        except queue.Empty:
            running_processes = get_running_processes(processes)

    return retval


def execute_section(section,
                    global_bear_list,
                    local_bear_list,
                    print_results,
                    log_printer):
    """
    Executes the section with the given bears.

    The execute_section method does the following things:
    1. Prepare a Process
      * Load files
      * Create queues
    2. Spawn up one or more Processes
    3. Output results from the Processes
    4. Join all processes

    :param section:          The section to execute.
    :param global_bear_list: List of global bears belonging to the section.
    :param local_bear_list:  List of local bears belonging to the section.
    :param print_results:    Prints all given results appropriate to the
                             output medium.
    :param log_printer:      The log_printer to warn to.
    :return:                 Tuple containing a bool (True if results were
                             yielded, False otherwise), a Manager.dict
                             containing all local results(filenames are key)
                             and a Manager.dict containing all global bear
                             results (bear names are key) as well as the
                             file dictionary.
    """
    local_bear_list = Dependencies.resolve(local_bear_list)
    global_bear_list = Dependencies.resolve(global_bear_list)

    try:
        running_processes = int(section['jobs'])
    except ValueError:
        log_printer.warn("Unable to convert setting 'jobs' into a number. "
                         "Falling back to CPU count.")
        running_processes = get_cpu_count()
    except IndexError:
        running_processes = get_cpu_count()

    processes, arg_dict = instantiate_processes(section,
                                                local_bear_list,
                                                global_bear_list,
                                                running_processes,
                                                log_printer)

    logger_thread = LogPrinterThread(arg_dict["message_queue"],
                                     log_printer)
    # Start and join the logger thread along with the processes to run bears
    processes.append(logger_thread)

    for runner in processes:
        runner.start()

    try:
        return (process_queues(processes,
                               arg_dict["control_queue"],
                               arg_dict["local_result_dict"],
                               arg_dict["global_result_dict"],
                               arg_dict["file_dict"],
                               print_results,
                               section,
                               log_printer),
                arg_dict["local_result_dict"],
                arg_dict["global_result_dict"],
                arg_dict["file_dict"])
    finally:
        logger_thread.running = False

        for runner in processes:
            runner.join()
