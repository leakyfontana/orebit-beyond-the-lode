"""
This scripts finds a graphic match for any combination of tiles around a block
The combination are stored as every alternative of 8 bits
"""

def generateAll256():
	with open("Data_stock.txt", "w") as f:
		for i in range(256):
			to_write = bin(i)
			to_write = to_write[2:]
			while len(to_write) < 8:
				to_write = "0" + to_write
			f.write(to_write + "\n")

def assignPicturesToData():
	with open("Data_stock.txt", "r") as data:
		with open("Linked_images.txt", "w") as res:
			for i in data.readlines():
				i = i.replace("\n", "")
				assignee = findLinkedImage(i)
				res.write("TunnelTiles.Add(\"" + i + "\", \"" + str(assignee) + "\");\n")

def findLinkedImage(data):
	a = int(data[0])
	b = int(data[1])
	c = int(data[2])
	d = int(data[3])
	f = int(data[4])
	g = int(data[5])
	h = int(data[6])
	i = int(data[7])
	if (b and d and f and h):
		return 46
	if (b and d and f and not h):
		return 45
	if (b and d and not f and h):
		return 44
	if (b and not d and f and h):
		return 43
	if (not b and d and f and h):
		return 42
	if (b and not d and not f and h):
		return 41
	if (not b and d and f and not h):
		return 40
	if (b and d and not f and not h and i):
		return 39
	if (b and not d and f and g and not h):
		return 38
	if (not b and c and d and not f and h):
		return 37
	if (a and not b and not d and f and h):
		return 36
	if (not b and c and d and not f and not h and i):
		return 35
	if (b and not d and not f and not h and g and i):
		return 34
	if (not b and not d and f and not h and a and g):
		return 33
	if (not b and not d and not f and h and a and c):
		return 32
	if (b and not d and f and not h):
		return 31
	if (b and d and not f and not h):
		return 30
	if (not b and d and not f and h):
		return 29
	if (not b and not d and f and h):
		return 28
	if (not b and d and not f and not h and i):
		return 27
	if (not b and not d and not f and h and c):
		return 26
	if (not b and not d and f and not h and a):
		return 25
	if (not b and d and not f and not h and i):
		return 24
	if (b and not d and not f and not h and i):
		return 23
	if (not b and d and not f and not h and c):
		return 22
	if (not b and not d and not f and h and a):
		return 21
	if (not b and not d and f and not h and g):
		return 20
	if (not b and d and not f and not h):
		return 19
	if (b and not d and not f and not h):
		return 18
	if (not b and not d and f and not h):
		return 17
	if (not b and not d and not f and h):
		return 16
	if (a and c and g and i):
		return 15
	if (a and c and i):
		return 14
	if (c and g and i):
		return 13
	if (a and g and i):
		return 12
	if (a and c and g):
		return 11
	if (a and i):
		return 10
	if (c and g):
		return 9
	if (a and g):
		return 8
	if (a and c):
		return 7
	if (c and i):
		return 6
	if (g and i):
		return 5
	if (c):
		return 4
	if (a):
		return 3
	if (g):
		return 2
	if (i):
		return 1
	if (not a and not b and not c and not d and not f and not g and not h and not i):
		return 0
	return -1

generateAll256()
assignPicturesToData()