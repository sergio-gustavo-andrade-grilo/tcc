SELECT time, machine_id, type,
       capacity.cpus   AS cpu_capacity,
       capacity.memory AS memory_capacity
FROM `google.com:google-cluster-data.clusterdata_2019_{cell}.machine_events`