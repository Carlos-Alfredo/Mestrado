import torch
import copy
from PIL import Image
from inference import image_haze_removel,image_haze_removal
import numpy as np
from torchvision.transforms import ToPILImage
# import metric
import torch.multiprocessing as mp
import lightdehazeNet
import time
from multiprocess import metric_calculation,list_split
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor

class EvolutionaryProcess:
	def __init__(self, starting_weight,population_size,parent_size,chance_of_mutation,max_rounds_without_improvement,image_path_list):
		self.round_count = 0
		self.starting_weight = starting_weight
		self.population_size = population_size
		self.parent_size = parent_size
		self.chance_of_mutation = chance_of_mutation
		self.apex = starting_weight['e_conv_layer8.weight']
		self.apex_timeline = []
		self.rounds_without_improvement = 0
		self.max_rounds_without_improvement = max_rounds_without_improvement
		self.population = [starting_weight['e_conv_layer8.weight']]
		for i in range(1,population_size):
			self.population.append(self.mutation(starting_weight['e_conv_layer8.weight'],1))
		self.images = []
		for img_path in image_path_list:
			img = Image.open(img_path)
			self.images.append(img)

	def mutation(self,weight,chance_of_mutation):
		dimensions = 	[weight.size(dim=0),
						weight.size(dim=1),
						weight.size(dim=2),
						weight.size(dim=3)]
		mutated_weight = weight.clone().detach()
		# mutated_weight = weight

		for j in range(0,dimensions[1]):
			# At a rate of chance_of_mutation * (1+rounds_without_improvement)
			if(torch.rand(1)<chance_of_mutation*(1+self.rounds_without_improvement)):
				# Creates a random mutation tensor in the interval of [-1,1]
				# mutation_tensor = torch.rand((dimensions[2],dimensions[3]),device='cuda') - torch.rand((dimensions[2],dimensions[3]),device='cuda')
				# if torch.rand(1)<0.5:
					# mutation_tensor = mutation_tensor.pow_(-1)
				# Creates a mutation sensor from a normal distribution
				mutation_tensor = torch.normal(mean=0,std=(1+self.rounds_without_improvement),size=(dimensions[2],dimensions[3]),device='cuda') + torch.ones((dimensions[2],dimensions[3]),dtype=torch.float64,device='cuda')
				# Mutates the tensor on all color channels
				for i in range(0,dimensions[0]):
					mutated_weight[i,j,:,:] = weight[i,j,:,:]*mutation_tensor
		return mutated_weight

	# parentA: weight
	# parentB: weight
	# chance of mutation: real number([0,1])
	# return: A new weight(child)

	def crossing(self,parentA,parentB):
		dimensions = 	[parentA.size(dim=0),
						parentA.size(dim=1),
						parentA.size(dim=2),
						parentA.size(dim=3)]
		
		# child = copy.deepcopy(parentA)
		child = parentA

		for i in range(0,dimensions[0]):
			for j in range(0,dimensions[1]):
				child[i,j,:,:] = (parentA[i,j,:,:] + parentB[i,j,:,:])/2

		return self.mutation(child,self.chance_of_mutation)



	# parents: List of weights that will originate the next generation
	# next_generation: List of weights representing the next generation

	# def mutation(self,weight):
	# 	for layer in weight.keys():
	# 		dimensions = 	[weight[layer].size(dim=0),
	# 						weight[layer].size(dim=1),
	# 						weight[layer].size(dim=2),
	# 						weight[layer].size(dim=3)]
	# 		mutated_weight = copy.deepcopy(weight)

	# 		for j in range(0,dimensions[1]):
	# 			# At a rate of chance_of_mutation
	# 			if(torch.rand(1)<self.chance_of_mutation):
	# 				# Creates a random mutation tensor in the interval of [-1,1]
	# 				mutation_tensor = torch.rand((dimensions[2],dimensions[3]),device='cuda:0') - torch.rand((dimensions[2],dimensions[3]),device='cuda:0')
	# 				# Mutates the tensor on all color channels
	# 				for i in range(0,dimensions[0]):
	# 					mutated_weight[layer][i,j,:,:] = weight[layer][i,j,:,:]*mutation_tensor

	# 		return mutated_weight

	# parentA: weight
	# parentB: weight
	# chance of mutation: real number([0,1])
	# return: A new weight(child)

	# def crossing(self,parentA,parentB):
	# 	for layer in parentA.keys():
	# 		dimensions = 	[parentA[layer].size(dim=0),
	# 						parentA[layer].size(dim=1),
	# 						parentA[layer].size(dim=2),
	# 						parentA[layer].size(dim=3)]
			
	# 		child = copy.deepcopy(parentA)

	# 		for i in range(0,dimensions[0]):
	# 			for j in range(0,dimensions[1]):
	# 				child[layer][i,j,:,:] = (parentA[layer][i,j,:,:] + parentB[layer][i,j,:,:])/2

	# 		return self.mutation(child)

	def next_generation(self,parents):
		next_generation = []
		for i in range(0,len(parents)):
			for j in range(0,len(parents)):
				if i!=j:
					next_generation.append(self.crossing(parents[i],parents[j]))
				else:
					next_generation.append(parents[i])
		return next_generation

	# population: List with the all the weights of a specific generation
	# img_path_list: list with the paths of the images that will be used for the test
	# returns: an array with the partial fitness score of each device ( population x number of metrics )

	def fitness_test(self,multiprocess_number):
		# cuda_device = torch.cuda.current_device()
		# torch.cuda.set_device(cuda_device)
		fitness_score = []
		max_eme = 0
		max_ssim = 0
		ld_net = lightdehazeNet.LightDehaze_Net().cuda()
		# ld_net.load_state_dict(self.starting_weight)
		for i in range(0,len(self.population)):
			# weight = dict({'e_conv_layer8.weight':self.population[i]})
			weight = self.starting_weight
			weight['e_conv_layer8.weight'] = self.population[i]
			# fitness_measure = []
			enhanced_imgs = []
			ld_net.load_state_dict(weight,strict=True)
			for img in self.images:
				dehaze_image_tensor = image_haze_removal(img,ld_net)
				dehaze_image_pil = dehaze_image_tensor
				dehaze_image_pil = dehaze_image_pil.cpu()
				dehaze_image_pil = dehaze_image_pil.squeeze(0)
				to_pil = ToPILImage()
				dehaze_image_pil = to_pil(dehaze_image_pil)
				enhanced_imgs.append(dehaze_image_pil)
			arguments = []
			for i in zip(enhanced_imgs,self.images):
				arguments.append(list(i))
			argument_splited = list_split(arguments,multiprocess_number)
			args = []
			for i in range(0,multiprocess_number):
				args.append((argument_splited[i],))

			pool = ThreadPoolExecutor()
			start = time.time()
			results = pool.map(metric_calculation, argument_splited)
			end = time.time()

			fitness_measure = []
			for i in results:
				fitness_measure += i
			fitness_measure = np.asarray(fitness_measure)
			fitness_measure_avg = np.mean(fitness_measure,axis=0)
			fitness_score.append(fitness_measure_avg)
		return np.asarray(fitness_score)

	# fitness_score_each_device: List with the fitness scores matrix(population_size x number of metrics) of each device
	# number_of_imgs_each_device: List with the number of images in each device
	# returns: numpy vector( population_size ) with the fitness score total of each individual
	def aggregate_fitness_score(self,fitness_score__total):
		fitness_score_normalized = fitness_score__total/np.max(fitness_score__total,axis=0)
		fitness_score_aggregated = fitness_score_normalized[:,0]*fitness_score_normalized[:,1]
		return fitness_score_aggregated

	def evolve(self,multiprocess_number):
		args_list = []  # List of arguments for the task function
		print("-> Round ",self.round_count)
		self.round_count += 1
		fitness_score=self.fitness_test(multiprocess_number)
		fitness_score_total = self.aggregate_fitness_score(fitness_score)
		population_ranking = np.argsort(fitness_score_total)[::-1]
		# equal = all(torch.allclose(self.apex[key], self.population[population_ranking[0]][key]) for key in self.apex.keys())
		if torch.equal(self.apex, self.population[population_ranking[0]]):
			self.rounds_without_improvement += 1
			print("There was no improvement this round!")
		else:
			self.apex = self.population[population_ranking[0]]
			self.rounds_without_improvement = 0
			print("New apex detected!")
		if self.rounds_without_improvement >= self.max_rounds_without_improvement:
			return 0
		else:
			self.apex_timeline.append(self.apex)
			surviving_population = []
			for i in range(0,self.parent_size):
				surviving_population.append(self.population[population_ranking[i]])
			self.population = self.next_generation(surviving_population)
			return 1
			# self.evolve()

	def return_apex(self):
		return self.apex

	def return_apex_timeline(self):
		return self.apex_timeline