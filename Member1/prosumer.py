#empty list to store all prosumers
prosumers = []

#list of the behavior types
behaviors = ["conservative", "aggressive", "green-oriented"]

# Low-consumption working household (24 hourly values)
low_working_load = [
    0.12, 0.10, 0.09, 0.09, 0.10, 0.15,
    0.28, 0.35, 0.18, 0.12, 0.10, 0.10,
    0.10, 0.10, 0.12, 0.12, 0.15, 0.20,
    0.35, 0.51, 0.42, 0.32, 0.18, 0.15
]
daily_consumption = sum(low_working_load)

print("Daily consumption:", daily_consumption, "kWh")


#Generate 100 prosumers
for i in range(100):   
    prosumer_id = f"P{i+1:03d}"

    prosumer = {
        "id": prosumer_id,
        "behavior": behaviors[i % 3]
    }

    prosumers.append(prosumer)

print(prosumers)