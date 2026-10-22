# -*- coding: utf-8 -*-
"""

Basic algorithm for FertiliCalc
calculation of N, P and K requirements

This new algorithm includes the new approaches in the second edition of Villalobos and Fereres (2024)
Principles of Agronomy for Sustainable Agriculture

Created on Wed Nov 20 12:54:59 2024

@author: F.Villalobos


"""
import csv
import pandas 
import numpy as np #importing the library
from numpy import genfromtxt

def readcsv(filename):
    data = pandas.read_csv(filename, header = None) 
    return(np.array(data)) #Please add four spaces here before this line

def readcsvb(filename):
    data = pandas.read_csv(filename) 
    return(np.array(data)) #Please add four spaces here before this line

p_lower = (0, 8., 10., 10., 10., 10., 12.)
p_higher = (0, 10., 12., 12., 12., 12., 20.)
k_lower = (0, 100., 150., 150., 150., 150., 200.)
k_higher = (0, 100., 175., 175., 175., 175., 300.)
fk_low = (0, 1.1, 1.1, 1.5, 1.5, 2., 2.5)
fk_hig = (0, 1.2, 1.2, 1.7, 1.7, 2., 5.)
bd = (0, 1.68, 1.56, 1.43, 1.41, 1.31, 1.21)
beta_pl = 0.8
efic = 0.8
soil_depth = 0.3
t_i = (0, -1.29, -0.84, -0.525, -0.25, 0., 0.25, 0.525, 0.84, 1.29)
n_end = 10.0
n_other = 10.0
fnr = 0.2
fnloss = 0.0
mw_n = 14
mw_p = 31
mw_k = 39.1
mw_ca = 40.08
mw_mg = 24.3
mw_s = 32
drain = (0, 5, 4, 3, 3, 2, 1)
clay = (0, 3, 10, 18, 15, 34, 60)
sand = (0, 92, 65, 42, 20, 32, 20)
cec_typ = (0, 30, 75, 100, 80, 220, 300)
factor_option_p = (1, 0.2, 0.36, 0.47, 0.48, 0.49, 0.52, 1.5, 1.6, 3.8, 15.0, 25.0)



df = pandas.read_csv('crop_data.csv', encoding='windows-1252', header=None)

crop_data = genfromtxt('crop_data.csv', delimiter=',')

name_crop = [list(x) for x in df.iloc[0:150, 0:1].values]
type_crop = [list(x) for x in df.iloc[0:150, 2:3].values]
#crop_type = [list(x) for x in df.iloc[0:150,2:3].values]

#print(name_crop[1])

#dm_h = [tuple(x) for x in df.iloc[0:149,4:5].values]
#crop_data = readcsvb('crop_data.csv')

dm_h = crop_data[:, [4]]
n_h = crop_data[:, [5]]
p_h = crop_data[:, [6]]
k_h = crop_data[:, [7]]
residue = crop_data[:, [8]]
dm_r = crop_data[:, [9]]
n_r = crop_data[:, [10]]
p_r = crop_data[:, [11]]
k_r = crop_data[:, [12]]
n_fix_c = crop_data[:, [13]]
n_n = crop_data[:, [14]]
n_x = crop_data[:, [15]]
hi_est = crop_data[:, [16]]
fres_est = crop_data[:, [17]]

n_max = np.zeros((10))
n_res = np.zeros((10))
p_res = np.zeros((10))
k_res = np.zeros((10))

crop_type = ['nothing']
latin_name = ['nothing']
dmh = np.zeros((10))
dmr = np.zeros((10))
n_fix_code = np.zeros((10))
n_min = np.zeros((10))
n_kg_crop = np.zeros((10))
yield_i = np.zeros((10))
n_kg_fix = np.zeros((10))
n_kg_min = np.zeros((10))
n_fert_i = np.zeros((10))

other_data = readcsv('input.txt')

crop_n = (other_data[:, [0]])
y = (other_data[:, [1]])
cv= (other_data[:, [2]])
h_i = (other_data[:, [3]])/100
fres = other_data[:, [4]]/100
n_harv = other_data[:, [5]]/100
p_harv = other_data[:, [6]]/100
k_harv = other_data[:, [7]]/100
burning = other_data[:, [8]]
#
soil_n = int(other_data[[0], [0]])
p_conc = float(other_data[[0], [1]])
k_conc = float(other_data[[0], [2]])
som = float(other_data[[0], [3]])
cec = float(other_data[[0], [4]])
ph = float(other_data[[0], [5]])
p_method = int(other_data[[0], [6]])
water_supply = int(other_data[[0], [7]])
strategy = int(other_data[[0], [8]])
tillage = int(other_data[[0], [9]])
n_rotation = int(other_data[[0], [10]])
crop_type = ['nothing', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n']
latin_name = ['nothing', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n']


for i in range(1, n_rotation+1):
    print(crop_n[i])
    n_res[i] = n_r[int(crop_n[i])] / 100
    p_res[i] = p_r[int(crop_n[i])] / 100
    k_res[i] = k_r[int(crop_n[i])] / 100
    dmh[i] = dm_h[int(crop_n[i])] / 100
    dmr[i] = dm_r[int(crop_n[i])] / 100   
    
    if n_res[i] == 0. or n_res[i]== 9.99 or str(n_res[i])== 'nan':
        n_res[i] = 1./100.
    if p_res[i] == 0. or p_res[i]== 9.99 or str(p_res[i])== 'nan':
        p_res[i] = 0.1/100.
    if k_res[i] == 0. or k_res[i]== 9.99 or str(k_res[i])== 'nan':
        k_res[i] = 1./100.
    if dmr[i] == 0. or dmr[i]== 9.99 or str(dmr[i])== 'nan':
        dmr[i] = dmh[i]
    crop_type[i] = type_crop[int(crop_n[i])]
    latin_name[i] = name_crop[int(crop_n[i])]
    n_fix_code[i] = n_fix_c[int(crop_n[i])]
    n_min[i] = n_n[int(crop_n[i])] / 100
    n_max[i] = n_x[int(crop_n[i])] / 100
bulk_dens = bd[soil_n]
#
#with open('o1.txt', 'w', newline='') as file:
with open('out.csv', 'w') as file:
    fieldnames = ['crop_name', 'N_fert_min kg N/ha','N_fert_max kg N/ha','N_fert_avg kg N/ha', 'P_fert kg P/ha', 'K_fert kg K/ha', 'P_fert kg P2O5/ha', 'K_fert kg K2O/ha']
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
for i in range(1, n_rotation+1):
    
    if strategy == 1 or strategy == 2:
        k_thres = k_lower[soil_n]
        fk = fk_low[soil_n]
    else:
        k_thres = k_higher[soil_n]
        fk = fk_hig[soil_n]
    ip = i - 1
    if ip == 0:
        ip = n_rotation
    burn = burning[i]
    n_fix = n_fix_code[i]
    if som == 0:
        som = 2.0
    if n_fix == 1:
        if "Forage_legume" in crop_type[i]:
            if som < 3:
                n_fix_per = 90
            else:
                n_fix_per = 60
        else:
            if som < 3:
                n_fix_per = 80
            else:
                n_fix_per = 50
    if strategy == 1 or strategy == 2:
        nc_y = n_min[i]
        nc_yp = n_min[ip]
    else:
        nc_y = n_harv[i]
        nc_yp = n_harv[ip]
#
#calculate N requirements for 10 levels of probability
#
    y_dm_med = y[i] * dmh[i]
    r_dm_med = y_dm_med * (1 - h_i[i]) / h_i[i]
    r_dm_medp = y[ip] * dmh[ip] * (1 - h_i[ip]) / h_i[ip]
    n_kg_crop[i] = (y_dm_med * nc_y + r_dm_med * n_res[i]) * (1 + fnr)
#    ' calculate N requirements for 10 levels of probability
#    cv=0
    for i_prob in range(1, 10):
        t=float(t_i[i_prob])
        y_mean= float(y[i])
        cvar=float(cv[i])
        yield_i[i_prob] = y_mean * (1 + cvar/ 100 * t)
        y_dm = yield_i[i_prob] * dmh[i]
        r_dm = y_dm * (1 - h_i[i]) / h_i[i]
        y_dmp = y[ip] * dmh[ip]
        r_dmp = y[ip] * dmh[ip] * (1 - h_i[ip]) / h_i[ip]
        ny = y_dm * nc_y
        nr = r_dm * n_res[i]
        nyp = y_dmp * nc_yp
        nrp = r_dmp * n_res[ip]
        kim = 0.5 + 0.2 * (n_fix_code[ip] + tillage)
        n_kg_min[i] = (1 - burn) * kim * fres[ip] * nrp
        n_fixation=0

        
        if "Trees" not in crop_type[i]:

            if n_fix == 0:
                n_fert = (n_end + (1 + fnr) * (ny + nr) - (1 - burn) * kim * \
                            fres[ip] * nrp - fnr * (nyp + nrp) - n_other) / (1 \
                            - fnloss)
            else:
                n_fixation = (1 + fnr) * (ny + nr) * n_fix_per / 100
                n_fert = (n_end + (1 + fnr) * (ny + nr) - (1 - burn) * kim * \
                            fres[ip] * nrp - fnr * (nyp + nrp) - n_other - \
                            n_fixation) / (1 - fnloss)
                n_kg_fix[i] = n_fixation
            if n_fert < 0:
                n_fert = 0.0
        else:

            #in the best case only 25% of vegetative biomass has to be supplied with N
            if fres[ip] * tillage == 1 and burn == 0 and water_supply == 1:
                coef_n_tree = 0.25
            else:
                coef_n_tree = 0.75

            n_fert = y_dm * (nc_y + beta_pl * (1 - h_i[i]) / h_i[i] * 0.01 * coef_n_tree) / efic
            
            if n_fert < 0:
                n_fert = 0
          
        if n_fert < 0:
            n_fert = 0
        n_fert_i[i_prob] = n_fert
 
    n_fert_avg = n_fert_i[5]
    n_fert_min=  n_fert_i[2]
    n_fert_max=  n_fert_i[8]

    y_dm = y_mean * dmh[i]
    r_dm = y_dm * (1 - h_i[i]) / h_i[i]

    p_conc = factor_option_p[p_method] * p_conc
            
    #calculate P limit according to PASA 2nd edition
    p_thres = 49 - 0.016 * 10 * clay[soil_n] - 3.81 * ph

    
    if "Tubers_roots" in crop_type[i]:    
        p_thres = p_thres + 7
    elif strategy == 3:
        p_thres = p_thres + 3
    if "Oryza sativa" in latin_name[i]:
        p_thres = 4
    p_exported = y_dm * p_harv[i] + r_dm * (1 - fres[i]) * p_res[i]
#
    p_limit_buildup=30
    if strategy == 4:
        p_buildup = 0
        p_rate = p_exported
    else:
        p_buildup= 10 * bulk_dens * soil_depth * (p_thres - p_conc)
        
        if p_buildup < 0:
            p_buildup = 0
        p_buildup_per_year = p_buildup/n_rotation
        if p_buildup_per_year > p_limit_buildup:
            p_buildup_per_year = p_limit_buildup 
            
        if strategy == 1:
            p_rate = p_buildup_per_year
        else:
            if p_conc < p_thres:
                p_rate = p_buildup_per_year + p_exported
            else:
                if p_conc < 2 * p_thres:
                    p_rate = p_exported
                else:
                    p_rate = 0.5 * p_exported
            
            

#
    k_exported = y_dm * k_harv[i] + r_dm * (1 - fres[i]) * k_res[i]
    n_exported = y_dm * n_harv[i] + r_dm * (1 - fres[i]) *n_res[i]+r_dm*fres[i]*n_res[i]*burn
#
    k_limit_buildup=60
    if strategy == 4:
        k_buildup = 0
        k_rate = p_exported
    else:
        k_buildup= 10 * bulk_dens * fk*soil_depth * (k_thres - k_conc)
        
        if k_buildup < 0:
            k_buildup = 0
        k_buildup_per_year = k_buildup/n_rotation
        if k_buildup_per_year > k_limit_buildup:
            k_buildup_per_year = k_limit_buildup 
            
        if strategy == 1:
            k_rate = k_buildup_per_year
        else:
            if k_conc < k_thres:
                k_rate = k_buildup_per_year + k_exported
            else:
                if soil_n < 6: 
                    if k_conc < 2 * k_thres:
                        k_rate = k_exported
                    else:
                        k_rate = 0.5 * k_exported
                else:
                    if k_conc < 1.5 * k_thres:
                        k_rate = k_exported
                    else:
                        k_rate = 0
           
#
    nombre = str(name_crop[int(crop_n[i])])
    string2 = nombre.replace('[', '')
    nombre = string2.replace(']', '')
#    with open('o1.txt', 'a', newline='\n') as file:
    with open('out.csv', 'a') as file:        
        writer = csv.writer(file, delimiter=',')
        p_fert=float(p_rate)
        p_fert_oxide= 2.29 * p_fert
        k_fert=float(k_rate)
        k_fert_oxide = 1.2047* k_fert
        data_list = (nombre, n_fert_min,n_fert_max, n_fert_avg, p_fert, k_fert,p_fert_oxide,k_fert_oxide)
        writer.writerow(data_list)

#
