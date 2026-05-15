import pickle

with open('data/cache/75cc963dd7df4423883d4b82d6d145c5_Chinh-sach-nghi-phep_1.docx.pkl', 'rb') as f:
    data = pickle.load(f)

print(data)