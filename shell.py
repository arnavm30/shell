import sys
import os
import subprocess as sbp
import glob
import shlex
import signal

# Job: a collection of piped processes or process group
class Job:
	def __init__(self, processes, isBackground = False):
		self.processes = processes # list of processes to run in tuple form
		self.popens = [] # list of popens
		self.pgid = None # procces group/job id
		self.isBackground = isBackground
		self.isSuspended = False

	def status(self):
		# Possible statuses: completed, running, terminated
		status = ''
		popens = self.popens
		for popen in popens:
			# returncode = None, Has not terminated (Running)
			# returncode = 0, Has completed (Done)
			# returncode = (-), Was terminated by signal or error (Terminated)
			if popen.poll() == None:
				status = 'Running'
				break
			elif isinstance(popen.poll(), int):
				if popen.poll() == 0:
					status = 'Done'
				elif popen.poll() != 0:
					status = 'Terminated'
		return status

BUILTINS = ['cd', 'pwd', 'fg', 'bg', 'jobs', 'help', 'exit']
jobs = []

#handle user generated interrupr when there's a job
def sigint_handler(signal_received, frame):
	raise Exception(signal_received)

# ignore user generated interrupt when there's no job
def sigint_ignore(signal_received, frame):
	print()
	raise Exception

# handle user generated stop when there's a job
def sigtstp_handler(signal_received, frame):
	raise Exception(signal_received)

# ignore user generated stop when there's no job
def sigtstp_ignore(signal_received, frame):
	print()
	raise Exception

# get job and determine if should be run in background
def get_input():
	background = False
	job_input = input(f'(rash) {os.getcwd()} {os.getlogin()}$ ').strip()
	if job_input[-1] == '&':
		background = True
		job_input = job_input[:-1]
	return job_input, background

# split jobs into processes and set up stdin and stdout for each process
def prepare_job(job_input):
	processes_input = job_input.split('|')
	processes = []
	for i, process_input in enumerate(processes_input):
		stdin = sbp.PIPE
		stdout = sbp.PIPE
		if '>' in process_input:
			j = process_input.index('>')
			if process_input[j+1] == '>':
				file_name = process_input[j+2:].strip()
				process_input = process_input[:j]
				stdout = open(file_name, 'ab')
			else:
				file_name = process_input[j+1:].strip()
				process_input = process_input[:j]
				stdout = open(file_name, 'wb')
		elif i != len(processes_input) - 1:
			stdout = open(f'/tmp/shell_piping{i}to{i+1}.txt', 'wb')

		if '<' in process_input:
			j = process_input.index('<')
			file_name = process_input[j+1:].strip()
			process_input = process_input[:j]
			try:
				stdin = open(file_name, 'rb')
			except:
				return f'{file_name}: no such file or directory'
		elif i != 0:
			stdin = open(f'/tmp/shell_piping{i-1}to{i}.txt', 'rb')

		processes.append((process_input, stdin, stdout))
	return processes

# changing directory
def cd(args):
	path = ''
	if len(args) == 0 or args[0] == '~':
		path = os.environ['HOME']
	elif args[0] == '..':
		path = os.path.dirname(os.getcwd())
	else:
		path = args[0]
	try:
		os.chdir(os.path.abspath(path))
	except Exception:
		return f'cd: no such file or directory: {path}'

# move last job or job of specified pid to background
def bg(args):
	job_to_bg = None
	if len(args) != 0:
		pid = args[0]
		for job in jobs:
			if pid == str(job.pgid):
				job_to_bg = job
	elif len(jobs) > 1:
		job_to_bg = jobs[-2]

	try:
		if job_to_bg.status() == 'Running':
			job_to_bg.isBackground = True
			job_to_bg.isSuspended = False
			for popen in job_to_bg.popens:
				try:
					popen.send_signal(signal.SIGCONT)
				except Exception:
					if job_to_bg.status() != 'Running':
						return 'bg: job has terminated'
	except Exception:
		return 'bg: no current job'

# move last job or job of specified pid to foreground
def fg(args):
	job_to_fg = None
	if len(args) != 0:
		pid = args[0]
		for job in jobs:
			if pid == str(job.pgid):
				job_to_fg = job
	elif len(jobs) > 1:
		job_to_fg = jobs[-2]

	try:
		if job_to_fg.status() == 'Running':
			job_to_fg.isBackground = False
			job_to_fg.isSuspended = False
			for popen in job_to_fg.popens:
				try:
					signal.signal(signal.SIGINT, sigint_handler)
					signal.signal(signal.SIGTSTP, sigtstp_handler)
					popen.send_signal(signal.SIGCONT)
					popen.wait()
				except Exception as e:
					if e.args[0] == signal.SIGINT:
						if not job_to_fg.isBackground:
							for popen in job_to_fg.popens:
								popen.send_signal(signal.SIGINT)
								return
					elif e.args[0] == signal.SIGTSTP:
						if not job_to_fg.isBackground:
							job_to_fg.isSuspended = True
							for popen in job_to_fg.popens:
								popen.send_signal(signal.SIGTSTP)
								return f'{job_to_fg.pgid} Suspended'
					if job_to_fg.status() != 'Running':
						return 'fg: job has terminated'
	except Exception:
		return 'fg: no current job'

# remove any no longer running jobs
def update_jobs():
	for job in jobs:
		if job.status() != 'Running':
			jobs.remove(job)

# return current jobs
def return_jobs():
	update_jobs()
	jobs_output = 'Position | PID  | Background  | Suspended  | Status \n'
	for pos, job in enumerate(jobs):
		jobs_output += (f'    {1 + pos}    | {job.pgid} |    {job.isBackground}    |    {job.isSuspended}    |  {job.status()}\n')
	return jobs_output

# kill any processes/jobs still running
def clean_jobs():
	for job in jobs:
		for popen in job.popens:
			if popen.poll() == None:
				popen.send_signal(signal.SIGINT)
	update_jobs()

# handle shell builtins
def builtins(command, args):
	if command == 'help':
		return 'rash: a simple Python shell.'
	elif command == 'pwd':
		return os.getcwd()
	elif command == 'cd':
		return cd(args)
	elif command == 'jobs':
		return return_jobs()
	elif command == 'bg':
		return bg(args)
	elif command == 'fg':
		return fg(args)
	elif command == 'exit':
		clean_jobs()
		print('[Process completed]')
		sys.exit(0)

# execute a command/process within a job
# issues with commands that require stdin i.e. cat when no stdin given
def execute_command(command, job, stdin, stdout):
	command = shlex.split(command)
	args = command[1:]
	command = command[0]
	for arg in args:
		if '*' in arg or '?' in arg:
			globbed_arg = glob.glob(f'{os.getcwd()}/{"".join(arg)}')
			i = args.index(arg)
			args.remove(arg)
			args = args[:i] + globbed_arg + args[i:]
	try:
		signal.signal(signal.SIGINT, sigint_handler)
		signal.signal(signal.SIGTSTP, sigtstp_handler)
		if command in BUILTINS:
			return builtins(command, args)
		else:
			popen = sbp.Popen([command] + args, stdin = stdin, stdout = stdout)
			job.popens.append(popen)
			if len(job.popens) == 1:
				job.pgid = popen.pid
			if not job.isBackground:
				popen.wait()
			if stdout == sbp.PIPE:
				return popen.communicate()[0].decode('utf-8')[:-1] # removing the new line at end
	except Exception as e:
		if e.args[0] == signal.SIGINT:
			if not job.isBackground:
				for popen in job.popens:
					popen.send_signal(signal.SIGINT)
					return
		elif e.args[0] == signal.SIGTSTP:
			if not job.isBackground:
				job.isSuspended = True
				for popen in job.popens:
					popen.send_signal(signal.SIGTSTP)
					return f'{job.pgid} Suspended'

# replace any commands within a command with the output
def subcommand(command, job):
	i = len(command) - 1 - command[::-1].index('($')
	j = command.index(')')
	inner_command = command[i+1:j]
	output = execute_command(inner_command, job, sbp.PIPE, sbp.PIPE)
	if output != None:
		return str(command[:i-1]) + str(output) + command[j+1:]
	else:
		return str(command[:i-1]) + str(command[j+1:])

# shell session loop
def loop():
	while True:
		signal.signal(signal.SIGINT, sigint_ignore)
		signal.signal(signal.SIGTSTP, sigtstp_ignore)
		try:
			job_input, background = get_input()
		except:
			continue
		processes = prepare_job(job_input)
		if isinstance(processes, str):
			print(processes)
			continue
		job = Job(processes, isBackground = background)
		jobs.append(job)
		for i, process in enumerate(processes):
			command = process[0]
			while '$(' in command:
				command = subcommand(command, job)
			output = execute_command(command, job, process[1], process[2])
			if output != None and i == len(processes) - 1:
				print(output)
		update_jobs()
loop()
