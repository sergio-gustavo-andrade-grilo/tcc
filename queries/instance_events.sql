SELECT time, type, collection_id, instance_index,
       resource_request.cpus   AS cpu_request,
       resource_request.memory AS memory_request,
       priority, scheduling_class, missing_type
FROM `google.com:google-cluster-data.clusterdata_2019_{cell}.instance_events`
WHERE collection_type = 0
  AND alloc_collection_id = 0
  AND ABS(MOD(FARM_FINGERPRINT(CAST(collection_id AS STRING)), {modulus})) = 0
  AND (time = 0 OR time BETWEEN {t_start} AND {t_end})