SELECT start_time, end_time, collection_id, instance_index,
       average_usage.cpus   AS avg_cpu,
       average_usage.memory AS avg_memory,
       maximum_usage.cpus   AS max_cpu,
       maximum_usage.memory AS max_memory
FROM `google.com:google-cluster-data.clusterdata_2019_{cell}.instance_usage`
WHERE collection_type = 0
  AND alloc_collection_id = 0
  AND ABS(MOD(FARM_FINGERPRINT(CAST(collection_id AS STRING)), {modulus})) = 0
  AND start_time BETWEEN {t_start} AND {t_end}