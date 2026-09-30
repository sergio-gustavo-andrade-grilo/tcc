# broker/src/main.py
from broker.src.adapters.synthetic_adapter import SyntheticAdapter


def main():
    adapter = SyntheticAdapter()
    
    print("--- MÁQUINAS ---")
    for machine in adapter.get_machines():
        print(machine)
        
    print("\n--- WORKLOADS ---")
    for workload in adapter.get_workloads():
        print(workload)
        
    print("\n--- USO ---")
    for usage in adapter.get_usage_samples():
        print(usage)

if __name__ == "__main__":
    main()