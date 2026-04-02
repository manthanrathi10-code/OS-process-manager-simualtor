import time
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

class Process:
    def __init__(self, pid, name, priority, burst_time, memory, arrival_tick):
        self.pid = pid
        self.name = name
        self.state = "NEW"  # NEW -> READY -> RUNNING -> WAITING -> TERMINATED
        self.priority = priority
        self.burst_time = burst_time
        self.remaining_time = burst_time
        self.arrival_tick = arrival_tick
        self.waiting_time = 0
        self.turnaround_time = 0
        self.memory = memory
        self.completion_tick = 0

    def to_dict(self):
        return {
            "pid": self.pid,
            "name": self.name,
            "state": self.state,
            "priority": self.priority,
            "burst_time": self.burst_time,
            "remaining_time": self.remaining_time,
            "arrival_time": self.arrival_tick * OSManager.tick_step_ms,
            "waiting_time": self.waiting_time,
            "turnaround_time": self.turnaround_time,
            "memory": self.memory
        }

class OSManager:
    tick_step_ms = 100
    memory_limit = 1024

    def __init__(self):
        self.processes = {}  # pid -> Process
        self.ready_queue = []  # list of pids
        self.running_pid = None
        self.tick_counter = 0
        self.algorithm = "FCFS"
        self.quantum = 100  # For Round Robin
        self.current_quantum_used = 0
        self.next_pid = 1
        self.activity_log_data = []

    def log(self, message):
        self.activity_log_data.append(f"[Tick {self.tick_counter:04d}] {message}")

    def memory_used(self):
        return sum(p.memory for p in self.processes.values() if p.state != "TERMINATED")

    def schedule_next(self):
        if self.running_pid is not None:
            return  # CPU is busy

        if not self.ready_queue:
            return  # Nothing to schedule

        # Algorithm logic
        if self.algorithm == "FCFS" or self.algorithm == "Round Robin":
            next_p = self.ready_queue.pop(0)
        elif self.algorithm == "SJF":
            self.ready_queue.sort(key=lambda pid: self.processes[pid].burst_time)
            next_p = self.ready_queue.pop(0)
        elif self.algorithm == "Priority":
            self.ready_queue.sort(key=lambda pid: self.processes[pid].priority, reverse=True)
            next_p = self.ready_queue.pop(0)

        self.running_pid = next_p
        self.processes[next_p].state = "RUNNING"
        self.current_quantum_used = 0
        self.log(f"Process {next_p} ({self.processes[next_p].name}) scheduled on CPU.")

    def step(self):
        # 1. Update waiting times for processes in ready queue
        for pid in self.ready_queue:
            self.processes[pid].waiting_time += self.tick_step_ms

        # 2. Advance running process
        if self.running_pid is not None:
            p = self.processes[self.running_pid]
            p.remaining_time -= self.tick_step_ms

            if p.remaining_time <= 0:
                # Process terminated
                p.remaining_time = 0
                p.state = "TERMINATED"
                p.completion_tick = self.tick_counter + 1
                p.turnaround_time = p.burst_time + p.waiting_time
                self.running_pid = None
                self.current_quantum_used = 0
                self.log(f"Process {p.pid} terminated.")
            else:
                if self.algorithm == "Round Robin":
                    self.current_quantum_used += self.tick_step_ms
                    if self.current_quantum_used >= self.quantum:
                        # Time quantum expired, context switch
                        p.state = "READY"
                        self.ready_queue.append(p.pid)
                        self.running_pid = None
                        self.current_quantum_used = 0
                        self.log(f"Process {p.pid} preempted (quantum expired).")

        self.tick_counter += 1
        self.schedule_next()

    def get_stats(self):
        total_created = len(self.processes)
        completed = sum(1 for p in self.processes.values() if p.state == "TERMINATED")
        completed_procs = [p for p in self.processes.values() if p.state == "TERMINATED"]
        
        avg_waiting = 0
        avg_turnaround = 0
        if completed_procs:
            avg_waiting = sum(p.waiting_time for p in completed_procs) / len(completed_procs)
            avg_turnaround = sum(p.turnaround_time for p in completed_procs) / len(completed_procs)
            
        total_time_ms = self.tick_counter * self.tick_step_ms
        total_cpu_time = sum((p.burst_time - p.remaining_time) for p in self.processes.values())
        if total_time_ms > 0:
            cpu_utilization = (total_cpu_time / total_time_ms) * 100
            if cpu_utilization > 100:
                cpu_utilization = 100
        else:
            cpu_utilization = 0

        return {
            "total_created": total_created,
            "completed": completed,
            "avg_waiting": round(avg_waiting, 2),
            "avg_turnaround": round(avg_turnaround, 2),
            "cpu_utilization": round(cpu_utilization, 2),
            "memory_used": self.memory_used(),
            "memory_limit": self.memory_limit
        }

os_manager = OSManager()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process/create", methods=["POST"])
def create_process():
    data = request.json
    name = data.get("name", f"Proc-{os_manager.next_pid}")
    # Handle empty string
    if not name.strip():
        name = f"Proc-{os_manager.next_pid}"
        
    priority = int(data.get("priority", 5))
    burst_time = int(data.get("burst_time", 1000))
    memory = int(data.get("memory", 128))

    if os_manager.memory_used() + memory > os_manager.memory_limit:
        return jsonify({"error": "Not enough memory. Try terminating processes."}), 400

    pid = os_manager.next_pid
    os_manager.next_pid += 1
    
    proc = Process(pid, name, priority, burst_time, memory, os_manager.tick_counter)
    proc.state = "READY"
    os_manager.processes[pid] = proc
    os_manager.ready_queue.append(pid)
    
    os_manager.log(f"Process {pid} ({name}) created.")
    
    if os_manager.running_pid is None:
        os_manager.schedule_next()
        
    return jsonify({"message": "Process created", "process": proc.to_dict()}), 201

@app.route("/process/terminate/<int:pid>", methods=["POST"])
def terminate_process(pid):
    if pid not in os_manager.processes:
        return jsonify({"error": "Process not found"}), 404
        
    p = os_manager.processes[pid]
    if p.state == "TERMINATED":
        return jsonify({"error": "Process already terminated"}), 400

    p.state = "TERMINATED"
    p.completion_tick = os_manager.tick_counter
    p.turnaround_time = (os_manager.tick_counter - p.arrival_tick) * os_manager.tick_step_ms
    
    if os_manager.running_pid == pid:
        os_manager.running_pid = None
        os_manager.current_quantum_used = 0
        os_manager.schedule_next()
    elif pid in os_manager.ready_queue:
        os_manager.ready_queue.remove(pid)
        
    os_manager.log(f"Process {pid} forcefully terminated.")
    return jsonify({"message": "Process terminated"}), 200

@app.route("/scheduler/step", methods=["POST"])
def scheduler_step():
    os_manager.step()
    return jsonify(get_state_impl())

@app.route("/scheduler/algorithm", methods=["POST"])
def set_algorithm():
    data = request.json
    algo = data.get("algorithm")
    valid_algos = ["FCFS", "SJF", "Round Robin", "Priority"]
    if algo in valid_algos:
        os_manager.algorithm = algo
        os_manager.log(f"Scheduling algorithm changed to {algo}.")
        
        if algo == "Round Robin":
            os_manager.current_quantum_used = 0
            
        return jsonify({"message": f"Algorithm set to {algo}"}), 200
    return jsonify({"error": "Invalid algorithm"}), 400

@app.route("/state", methods=["GET"])
def get_state():
    return jsonify(get_state_impl())

def get_state_impl():
    processes = [p.to_dict() for p in os_manager.processes.values()]
    recent_logs = os_manager.activity_log_data[-50:]
    
    return {
        "tick": os_manager.tick_counter,
        "time_ms": os_manager.tick_counter * os_manager.tick_step_ms,
        "algorithm": os_manager.algorithm,
        "processes": processes,
        "ready_queue": os_manager.ready_queue,
        "running_pid": os_manager.running_pid,
        "stats": os_manager.get_stats(),
        "logs": recent_logs
    }

@app.route("/reset", methods=["POST"])
def reset():
    global os_manager
    os_manager = OSManager()
    os_manager.log("System reset.")
    return jsonify({"message": "System reset ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
