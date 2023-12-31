##09/05/2018
##@@author: Simon (Chong) Chu, DBMI, Harvard Medical School
##@@contact: chong.simon.chu@gmail.com

#this module is designed for cancer (case-control) genomes

import os
from optparse import OptionParser
from x_clip_disc_filter import *
from x_genotype_feature import *
from x_transduction import *
from x_orphan_transduction import *

####
class CaseControlMode():
    def __init__(self, sf_ref, s_wfolder, n_jobs):
        self.s_wfolder=s_wfolder
        if os.path.exists(s_wfolder)==False:
            self.s_wfolder="./"
        elif s_wfolder[-1]!="/":
            s_wfolder+="/"
        self.sf_ref=sf_ref
        self.n_jobs=n_jobs

        self.iextnd = 400  ###for each site, re-collect reads in range [-iextnd, iextnd], this around ins +- 3*derivation
        self.bin_size = 50000000  # block size for parallelization
        self.bmapped_cutoff = 0.65
        self.i_concord_dist = 550  # this should be the 3*std_deviation, used to cluster disc reads on the consensus
        self.f_concord_ratio = 0.45
        self.CLIP_CONSIST_DIST=35
        self.DISC_CONSIST_DIST=50

####
    def set_parameters(self, iextnd, bin_size, bmapped_cutoff, i_concord_dist, f_concord_ratio):
        self.iextnd=iextnd
        self.bin_size=bin_size
        self.bmapped_cutoff=bmapped_cutoff
        self.i_concord_dist=i_concord_dist
        self.f_concord_ratio=f_concord_ratio

    # load the sites from file
    def load_sites(self, sf_ce):##
        m_MEI = {}
        with open(sf_ce) as fin_ce:
            for line in fin_ce:
                fields = line.split()
                chrm = fields[0]
                pos = int(fields[1])
                sinfo="\t".join(fields[2:])
                if chrm not in m_MEI:
                    m_MEI[chrm] = {}
                if pos not in m_MEI[chrm]:
                    m_MEI[chrm][pos] = sinfo
        return m_MEI


    #extract genotype features and left/right region depths of given sites (this is for the control sample)
    def extract_sites_raw_gntp_feature_depth(self, sf_candidate_list, sf_bam_list):#
        # get the depth information
        rd = ReadDepth(self.s_wfolder, self.n_jobs, self.sf_ref)
        search_win = global_values.COV_SEARCH_WINDOW  # this region is to collect the reads, by default 1000
        focal_win = global_values.LOCAL_COV_WIN  # this region is used to search for coverage island, by default 900
        focal_win2 = global_values.COV_ISD_CHK_WIN  # this region is to calculate the local coverage, by default 200
        m_sites=self.load_sites(sf_candidate_list)
        m_read_depth = rd.calc_coverage_of_two_regions(m_sites, sf_bam_list, search_win,
                                                       focal_win, focal_win2)
        sf_depth=sf_candidate_list + ".read_depth"
        rd.dump_coverage_info(m_read_depth, sf_depth)

        # get the genotype information
        x_gntper = XGenotyper(self.sf_ref, self.s_wfolder, self.n_jobs)
        is_extnd = global_values.DFT_IS
        sf_gntp_feature = sf_candidate_list + ".gntp.features"
        x_gntper.call_genotype(sf_bam_list, sf_candidate_list, is_extnd, sf_gntp_feature)
        # load in features, also filter out sites with very large clipped reads at the breakpoints
        i_total_cov = global_values.AVE_COVERAGE
        i_max_cov = global_values.MAX_COV_TIMES * i_total_cov
        m_gntp_info = x_gntper.load_in_features_from_file_with_cov_cutoff(sf_gntp_feature, i_max_cov)
        return m_read_depth, m_gntp_info

####
    ####nclip, ndisc are the cutoff when calling somatic events
    #sf_bam_list is in format: s_id sf_control1 sf_control2
    def call_somatic_TE_insertion(self, sf_bam_list, sf_case_candidates, extnd, nclip_cutoff, ndisc_cutoff,
                                  npolyA_cutoff, sf_rep_cns, sf_flank, i_flk_len, bin_size, sf_out, b_tumor=False):
        #separate the transduction and non-transduction cases
        #for non-transduction cases:
        xclip_disc = XClipDiscFilter(sf_bam_list, self.s_wfolder, self.n_jobs, self.sf_ref)
        sf_non_td = sf_case_candidates + ".non_td.tmp"
        sf_td=sf_case_candidates+".td.tmp"
        sf_td_sibling=sf_case_candidates+".td_sibling.tmp"
        sf_orphan=sf_case_candidates+".orphan.tmp"
        xclip_disc.sprt_TEI_to_td_orphan_non_td(sf_case_candidates, sf_non_td, sf_td, sf_td_sibling, sf_orphan)

        #parse, realign, cluster clip and discordant reads to consensus, and save to a file
        sf_tmp_cluster=sf_out+".candidate_somatic_cluster_from_ctrl.txt"
        m_clip_cluster_non_td=xclip_disc.call_clip_disc_cluster(sf_non_td, self.iextnd, self.bin_size, sf_rep_cns,
                                          self.bmapped_cutoff,self.i_concord_dist, self.f_concord_ratio, nclip_cutoff,
                                          ndisc_cutoff, self.s_wfolder, sf_tmp_cluster)
        #m_read_depth, m_gntp_info=self.extract_sites_raw_gntp_feature_depth(sf_non_td, sf_bam_list) ####

        #First round filter for TD cases (this is for all TDs, including )
        # parse, realign, cluster clip and discordant reads to consensus, and save to a file
        sf_tmp_td_cluster = sf_out + ".candidate_somatic_td_cluster_from_ctrl.txt"
        m_clip_cluster_td = xclip_disc.call_clip_disc_cluster(sf_td, self.iextnd, self.bin_size, sf_rep_cns,
                                                                  self.bmapped_cutoff, self.i_concord_dist,
                                                                  self.f_concord_ratio, nclip_cutoff,
                                                                  ndisc_cutoff, self.s_wfolder, sf_tmp_td_cluster)#
        #m_read_depth_td, m_gntp_info_td = self.extract_sites_raw_gntp_feature_depth(sf_td, sf_bam_list)

        #Second round filter for TD cases
        #parse, realign to flanking sequences, and save to file
        xtd=XTransduction(self.s_wfolder, self.n_jobs, self.sf_ref)
        sf_tmp_cluster_td=sf_out+".candidate_somatic_cluster_from_ctrl_td.txt"
        m_td_cluster, m_td_polyA=xtd.collect_realign_reads(sf_td, sf_case_candidates, xclip_disc, sf_flank,
                                                           i_flk_len, extnd, bin_size, ndisc_cutoff, sf_rep_cns,
                                                           sf_tmp_cluster_td)
####
        with open(sf_out+".tmp_ctrl_clip_polyA", "w") as fout_clip_polyA:
            for ins_chrm in m_td_polyA:
                for ins_pos in m_td_polyA[ins_chrm]:
                    rcd=m_td_polyA[ins_chrm][ins_pos]
                    sinfo="{0}\t{1}\t{2}\t{3}\t{4}\t{5}\t{6}\t\t{7}\n".format(ins_chrm, ins_pos, rcd[0], rcd[1], rcd[2],
                                                                              rcd[3], rcd[4], rcd[5])
                    fout_clip_polyA.write(sinfo)
####
        # Comment (09-15-20): it is possible a wrongly annotated sibling, but actually a germline SV
        # we need a module to filter out these events

        #collect features for orphan cases from control bam
        #check each sites and filter out germline cases
        xorphan=XOrphanTransduction(self.s_wfolder, self.n_jobs, self.sf_ref)

        m_need_filter_out=xorphan.check_features_for_given_sites(sf_orphan, sf_bam_list, nclip_cutoff, ndisc_cutoff)

        #(this is for sibling cases, we add another checking 09-01-2020)
        m_filter_out_sibling = xorphan.check_features_for_given_sites(sf_td_sibling, sf_bam_list, nclip_cutoff,
                                                                      ndisc_cutoff)#
####
        #print m_clip_cluster
        #parse out the somatic events
        m_cluster_info=xclip_disc.load_TEI_info_from_file(sf_tmp_cluster)
        m_cluster_info_td = xclip_disc.load_TEI_info_from_file(sf_tmp_td_cluster)
        sf_before_final=sf_out+".before_final_filter"
        m_unique_tmp={}
        with open(sf_before_final, "w") as fout_rslt:
            with open(sf_non_td) as fin_sites:
                for line in fin_sites:
                    fields=line.split()
                    chrm = fields[0]
                    pos = int(fields[1])
                    if chrm not in m_unique_tmp:
                        m_unique_tmp[chrm]={}
                    if pos in m_unique_tmp[chrm]:
                        continue
                    else:
                        m_unique_tmp[chrm][pos]=1
                    if self.pass_cns_chk(m_cluster_info, m_clip_cluster_non_td, fields, npolyA_cutoff)==True:
                        fout_rslt.write(line)
            with open(sf_td) as fin_sites:
                for line in fin_sites:
                    l_fields=line.split()
                    chrm=l_fields[0]
                    pos=int(l_fields[1])
                    if chrm not in m_unique_tmp:
                        m_unique_tmp[chrm]={}
                    if pos in m_unique_tmp[chrm]:
                        continue
                    else:
                        m_unique_tmp[chrm][pos]=1
                    if self.pass_td_chk(m_td_cluster, m_td_polyA, l_fields, npolyA_cutoff)==True:
                        if self.pass_cns_chk(m_cluster_info_td, m_clip_cluster_td, l_fields, npolyA_cutoff) == True:
                            if (chrm in m_filter_out_sibling) and (pos in m_filter_out_sibling[chrm]):
                                continue
                            fout_rslt.write(line)
            with open(sf_orphan) as fin_orphan:
                for line in fin_orphan:
                    fields=line.split()
                    chrm=fields[0]
                    pos=int(fields[1])
                    if chrm not in m_unique_tmp:
                        m_unique_tmp[chrm]={}
                    if pos in m_unique_tmp[chrm]:
                        continue
                    else:
                        m_unique_tmp[chrm][pos]=1
                    if (chrm in m_need_filter_out) and (pos in m_need_filter_out[chrm]):
                        continue
                    fout_rslt.write(line)

        f_disc_ef_ratio=0.1 #minimum effective discordant pair ratio
        f_ef_disc_cutoff=0.05 #minimal AF of effective discordant pairs in case
        f_disc_cutoff= 0.15#minimal AF of discordant pairs in case
        f_case_ctrl_cutoff= 0.35#maximum ctrl-ratio/case-ratio
        f_ctrl_clip_ratio=0.75 #maximum clip ratio (higher means lots of clipped reads at the breakpoints)
        f_ctrl_raw_clip_flex_ratio=0.35 #this is a flexible ratio, if case has > ratio, and in case no polyA reads
        f_ctrl_polyA_cutoff=0.3
        f_case_raw_clip_cutoff=0.05
        self.filter_by_case_ctrl_disc_depth_ratio(sf_before_final, sf_bam_list, f_disc_ef_ratio, f_ef_disc_cutoff, f_disc_cutoff, f_case_raw_clip_cutoff,
                                                  f_case_ctrl_cutoff, f_ctrl_clip_ratio, f_ctrl_raw_clip_flex_ratio, f_ctrl_polyA_cutoff, sf_out)
####
####
    #this is to filter out FP germline events by comparing case control disc-depth ratio
    def filter_by_case_ctrl_disc_depth_ratio(self, sf_candidate, sf_ctrl_bam, f_disc_ef_ratio, f_ef_disc_depth_cutoff, f_disc_cutoff, f_case_raw_clip_cutoff,
                                        f_case_ctrl_cutoff, f_ctrl_clip_ratio, f_ctrl_raw_clip_flex_ratio, f_ctrl_polyA_cutoff, sf_out):#
        ####
        m_depth_ctrl, m_feature_ctrl = self.extract_sites_raw_gntp_feature_depth(sf_candidate, sf_ctrl_bam)
        with open(sf_candidate) as fin_sites, open(sf_out,"w") as fout_new, open(sf_out+".filter_log","w") as fout_log:
            for line in fin_sites:
                b_trsdct=True
                b_orphan=False
                b_sibling=False
                if global_values.NOT_TRANSDUCTION in line:
                    b_trsdct=False
                if global_values.ORPHAN_LABEL in line:
                    b_orphan=True
                if global_values.SIBLING_LABEL in line:
                    b_sibling=True
                fields=line.split()
                ins_chrm=fields[0]
                ins_pos=int(fields[1])#

                n_l_ef_disc=int(fields[7])
                n_r_ef_disc=int(fields[8])
                # for case sample
                n_lpolyA = int(fields[9])
                n_rpolyA = int(fields[10])
                f_lcov=float(fields[11])
                f_rcov=float(fields[12])##

                n_ef_clip = int(fields[5]) + int(fields[6])#
                n_ef_disc = int(fields[7]) + int(fields[8])
                n_clip = int(fields[35])
                n_full_map = int(fields[36])
                n_raw_lclip_case=int(fields[37])
                n_raw_rclip_case=int(fields[38])#
                n_disc = int(fields[39])
                n_concod = int(fields[40])#

                if f_lcov+f_rcov <=0.0000000001:#
                    continue
                f_ef_disc_ratio_case=float(n_ef_disc)*2/(f_lcov+f_rcov)
                if f_ef_disc_ratio_case < f_ef_disc_depth_cutoff:
                    fout_log.write("%s:%d is filtered out as ef_disc_ratio_case is small!\n" % (ins_chrm, ins_pos))
                    continue

                #this filter should be moved to the calling step
                ##if any side of the effect discordant pairs ratio is low, then filter out
                if b_orphan==True and \
                        (((f_lcov>0) and (float(fields[7])/f_lcov < f_ef_disc_depth_cutoff)) or
                         ((f_rcov>0) and (float(fields[8])/f_rcov < f_ef_disc_depth_cutoff))):
                    fout_log.write("%s:%d (orpha) is filtered out as ef_disc_ratio_case is small!\n" % (ins_chrm, ins_pos))
                    continue
                #request both side should have raw clip reads
                elif b_orphan==True and \
                        (((f_lcov>0) and (float(n_raw_lclip_case)/f_lcov < f_case_raw_clip_cutoff)) or
                         ((f_rcov>0) and (float(n_raw_rclip_case)/f_rcov < f_case_raw_clip_cutoff))):
                    fout_log.write(
                        "%s:%d (orpha) is filtered out as raw clip ratio is small!\n" % (ins_chrm, ins_pos))
                    continue

                f_disc_ratio_case=float(n_disc)*2/(f_lcov+f_rcov)#
                if f_disc_ratio_case < f_disc_cutoff:####
                    fout_log.write("%s:%d is filtered out as disc_ratio_case is small!\n" % (ins_chrm, ins_pos))
                    continue

                if n_disc<=0:
                    fout_log.write("%s:%d is filtered out as no discordant reads!\n" % (ins_chrm, ins_pos))
                    continue
                f_ef_disc_raw_disc_ratio=float(n_l_ef_disc+n_r_ef_disc)/float(n_disc)
                if (f_ef_disc_raw_disc_ratio<f_disc_ef_ratio) and b_orphan==False and b_sibling==False:#filter by checking effective discordant rate
                    fout_log.write("%s:%d is filtered out as ef_disc_raw_disc_ratio is small!\n" % (ins_chrm, ins_pos))
                    continue

                f_clip_ratio_case=float(n_raw_lclip_case+n_raw_rclip_case)*2/(f_lcov+f_rcov)#
                f_ef_clip_ratio_case=float(n_ef_clip)*2/(f_lcov+f_rcov)#
                f_polyA_ratio_case=1
                if n_ef_clip>0:#
                    f_polyA_ratio_case = float(n_lpolyA + n_rpolyA) / (n_ef_clip)

                #for control sample
                if (ins_chrm not in m_feature_ctrl) or (ins_pos not in m_feature_ctrl[ins_chrm]):
                    fout_log.write("%s:%d is filtered out as site is not in m_feature_ctrl!\n" % (ins_chrm, ins_pos))
                    continue
                n_af_clip_ctrl = m_feature_ctrl[ins_chrm][ins_pos][0]
                n_full_map_ctrl = m_feature_ctrl[ins_chrm][ins_pos][1]
                n_raw_lclip_ctrl = m_feature_ctrl[ins_chrm][ins_pos][2]
                n_raw_rclip_ctrl = m_feature_ctrl[ins_chrm][ins_pos][3]
                n_disc_pairs_ctrl = m_feature_ctrl[ins_chrm][ins_pos][4]
                n_concd_pairs_ctrl = m_feature_ctrl[ins_chrm][ins_pos][5]
                n_disc_large_indel_ctrl = m_feature_ctrl[ins_chrm][ins_pos][6]
                s_clip_lens_ctrl = m_feature_ctrl[ins_chrm][ins_pos][7]
                n_polyA_ctrl=m_feature_ctrl[ins_chrm][ins_pos][8]
                if (ins_chrm not in m_depth_ctrl) or (ins_pos not in m_depth_ctrl[ins_chrm]):
                    fout_log.write("%s:%d is filtered out as site is not in m_depth_ctrl!\n" % (ins_chrm, ins_pos))
                    continue
                f_lcov_ctrl=m_depth_ctrl[ins_chrm][ins_pos][0]
                f_rcov_ctrl=m_depth_ctrl[ins_chrm][ins_pos][1]

                if f_lcov_ctrl+f_rcov_ctrl<=0.0000000001:
                    fout_log.write("%s:%d is filtered out as ctrl depth is 0!\n" % (ins_chrm, ins_pos))
                    continue
                f_disc_ratio_ctrl=float(n_disc_pairs_ctrl)*2/(f_lcov_ctrl+f_rcov_ctrl)
                f_clip_ratio_ctrl=float(n_raw_lclip_ctrl+n_raw_rclip_ctrl)*2/(f_lcov_ctrl+f_rcov_ctrl) ###
                f_ef_clip_ratio_ctrl=float(n_af_clip_ctrl)*2/(f_lcov_ctrl+f_rcov_ctrl)####
                f_polyA_ratio_ctrl = float(n_polyA_ctrl)/(f_lcov_ctrl+f_rcov_ctrl)

                if b_trsdct==True:#transduction events (including cannonical, orphan and sibling events)
                    if (f_disc_ratio_ctrl/f_disc_ratio_case > f_case_ctrl_cutoff) and \
                            (f_clip_ratio_ctrl/f_clip_ratio_case > f_case_ctrl_cutoff):#indicates happen in ctrl
                        fout_log.write("%s:%d (transduction) is filtered out as event have disc and clip in ctrl!\n" % (
                            ins_chrm, ins_pos))
                        continue
                else:#cannonical events, we check the effective disc and clip
                    if (f_disc_ratio_ctrl/f_disc_ratio_case > f_case_ctrl_cutoff) and \
                            (f_ef_clip_ratio_ctrl/f_ef_clip_ratio_case > f_case_ctrl_cutoff):#indicates happen in ctrl
                        fout_log.write("%s:%d is filtered out as event have disc and clip in ctrl!\n" % (
                        ins_chrm, ins_pos))
                        continue

                ## use polyA-depth ration to filter out FP ones
                # if (f_polyA_ratio_case > 0) and (f_polyA_ratio_ctrl / f_polyA_ratio_case > f_case_ctrl_polyA_cutoff):
                #     fout_log.write("%s:%d is filtered out at polyA ratio step!\n" % (ins_chrm, ins_pos))
                #     continue#
                if (f_polyA_ratio_ctrl>f_ctrl_polyA_cutoff):#(by default 0.3)
                    fout_log.write("%s:%d is filtered out at polyA ratio step!\n" % (ins_chrm, ins_pos))
                    continue

                #use clip/full-map ratio in ctrl to filter out false positives ones
                #filter out if in ctrl: 1) clip/full-map ratio is high (by default 75%) and also 2) high discordant rate
                if ((n_af_clip_ctrl+n_full_map_ctrl)==0 or
                    float(n_af_clip_ctrl)/(n_af_clip_ctrl+n_full_map_ctrl) > f_ctrl_clip_ratio) and (f_disc_ratio_ctrl>f_disc_cutoff):#
                    fout_log.write("%s:%d is filtered out at ctrl clip/full-map ratio step!\n" % (ins_chrm, ins_pos))
                    continue

                #use raw-clip/full-map ratio in ctrl to filter out false positive ones
                n_raw_clip_ctrl=n_raw_lclip_ctrl+n_raw_rclip_ctrl
                f_raw_clip_ratio_ctrl=0
                if (n_raw_clip_ctrl + n_full_map_ctrl) > 0:
                    f_raw_clip_ratio_ctrl=float(n_raw_clip_ctrl) / float(n_raw_clip_ctrl + n_full_map_ctrl)
                #in ctrl, lots of raw clip reads, and also many discordant reads (or lots of polyA), then filter out
                f_ctrl_polyA_clip_ratio=0
                if n_raw_clip_ctrl>0:
                    f_ctrl_polyA_clip_ratio=float(n_polyA_ctrl)/float(n_raw_clip_ctrl)##
                b_ctrl_clip_polyA_dominant=False
                if f_ctrl_polyA_clip_ratio>(f_ctrl_clip_ratio/2):
                    b_ctrl_clip_polyA_dominant=True
                if (((n_raw_clip_ctrl + n_full_map_ctrl) == 0) or (f_raw_clip_ratio_ctrl > f_ctrl_clip_ratio)) and \
                        ((f_disc_ratio_ctrl>f_disc_cutoff) or (b_ctrl_clip_polyA_dominant==True and n_disc_pairs_ctrl>0)):#by default disc_ratio >0.3 or
                    fout_log.write("%s:%d is filtered out at ctrl raw clip step!\n" % (ins_chrm, ins_pos))
                    continue

                #if ctrl-raw-clip ratio > cutoff(default 35%) and non-polyA detected in case, then filter out
                if (n_lpolyA+n_rpolyA==0) and (f_raw_clip_ratio_ctrl>f_ctrl_raw_clip_flex_ratio):
                    fout_log.write("%s:%d is filtered out at case_polyA and ctrl raw clip step2!\n" % (ins_chrm, ins_pos))
                    continue

                fout_new.write(line.rstrip()+"\n")##

####
####
    #check by collecting clip disc reads from control, and align them to consensus
    #if: 1) disc reads form same cluster
    #    2) clip reads form same cluster
    #    3) polyA support
    def pass_cns_chk(self, m_cluster, m_clip_cluster, l_case_site_info, n_polyA_cutoff):
        ins_chrm=l_case_site_info[0]
        ins_pos=int(l_case_site_info[1])
        s_case_lclip_clst = l_case_site_info[19]
        s_case_rclip_clst = l_case_site_info[20]
        s_case_ldisc_clst = l_case_site_info[21]
        s_case_rdisc_clst = l_case_site_info[22]

        if (ins_chrm in m_clip_cluster) and (ins_pos in m_clip_cluster[ins_chrm]):
            s_ctrl_lclip_clst = str(m_clip_cluster[ins_chrm][ins_pos][2]) + ":" + str(
                m_clip_cluster[ins_chrm][ins_pos][3])
            s_ctrl_rclip_clst = str(m_clip_cluster[ins_chrm][ins_pos][4]) + ":" + \
                                str(m_clip_cluster[ins_chrm][ins_pos][5])
            b_clip_consist = self._is_clip_cluster_consist(s_case_lclip_clst, s_case_rclip_clst,
                                                           s_ctrl_lclip_clst, s_ctrl_rclip_clst)
            if b_clip_consist == True:
                return False

        if (ins_chrm not in m_cluster) or (ins_pos not in m_cluster[ins_chrm]):
            print("{0}:{1} doesn't form clip and disc cluster!".format(ins_chrm, ins_pos))
            return True

        (nlclip, nrclip, nldisc, nrdisc, nlpolyA, nrpolyA, s_cns_lclip, s_cns_rclip,
         s_cns_ldisc, s_cns_rdisc)=m_cluster[ins_chrm][ins_pos]
        b_polyA=False
        if nlpolyA>n_polyA_cutoff and nrpolyA>n_polyA_cutoff:#both side polyA
            b_polyA=True
            return False

        b_clip_consist=self._is_clip_cluster_consist(s_case_lclip_clst, s_case_rclip_clst, s_cns_lclip, s_cns_rclip)
        b_disc_consist=self._is_disc_cluster_consist(s_case_ldisc_clst, s_case_rdisc_clst, s_cns_ldisc, s_cns_rdisc)

        if b_clip_consist or b_disc_consist:
            return False
        return True
####
    ####
    def pass_td_chk(self, m_td_cluster, m_td_polyA, l_fields, n_polyA_cutoff):
        #1. check whether they are of the same disc cluster
        ins_chrm=l_fields[0]
        ins_pos=int(l_fields[1])
        s_case_src=l_fields[23]

        if (ins_chrm not in m_td_cluster) or (ins_pos not in m_td_cluster[ins_chrm]):
            return True
        s_ctrl_src=m_td_cluster[ins_chrm][ins_pos][0]
        if (s_ctrl_src in s_case_src) or (s_ctrl_src == s_case_src) or (s_case_src in s_ctrl_src):
            print("{0}:{1} transduction is filtered out, as it has the same source as control".format(ins_chrm, ins_pos))
            return False

        #2. check polyA support
        if (ins_chrm in m_td_polyA) and (ins_pos in m_td_polyA[ins_chrm]):
            n_polyA=m_td_polyA[ins_chrm][ins_pos][0]+m_td_polyA[ins_chrm][ins_pos][1]
            n_polyT=m_td_polyA[ins_chrm][ins_pos][2]+m_td_polyA[ins_chrm][ins_pos][3]
            if n_polyA>=n_polyA_cutoff or n_polyT>=n_polyA_cutoff:
                print("{0}:{1} transduction is filtered out, as there are polyA tails found in control".format(ins_chrm, ins_pos))
                return False
        return True
####
####
    def _is_clip_cluster_consist(self, s_case_lclip_clst, s_case_rclip_clst, s_ctrl_lclip_clst, s_ctrl_rclip_clst):
        l_ctrl_lclip=s_ctrl_lclip_clst.split(":")
        l_ctrl_rclip=s_ctrl_rclip_clst.split(":")
        l_case_lclip=s_case_lclip_clst.split(":")
        l_case_rclip=s_case_rclip_clst.split(":")

        b_l_consist=False
        b_r_consist=False

        if s_ctrl_rclip_clst != "-1:-1" and s_case_rclip_clst!="-1:-1":
            if abs(int(float(l_case_rclip[0]))-int(float(l_ctrl_rclip[0]))) < self.CLIP_CONSIST_DIST or \
                            abs(int(float(l_case_rclip[1]))-int(float(l_ctrl_rclip[1]))) < self.CLIP_CONSIST_DIST:
                b_r_consist = True
        if s_ctrl_lclip_clst != "-1:-1" and s_case_lclip_clst != "-1:-1":
            if abs(int(float(l_case_lclip[0]))-int(float(l_ctrl_lclip[0]))) < self.CLIP_CONSIST_DIST or \
                            abs(int(float(l_case_lclip[1]))-int(float(l_ctrl_lclip[1]))) < self.CLIP_CONSIST_DIST:
                b_l_consist = True
        if s_ctrl_rclip_clst != "-1:-1" and s_case_rclip_clst!="-1:-1":
            if abs(int(float(l_case_rclip[0]))-int(float(l_ctrl_rclip[1]))) < self.CLIP_CONSIST_DIST or \
                            abs(int(float(l_case_rclip[1]))-int(float(l_ctrl_rclip[0]))) < self.CLIP_CONSIST_DIST:
                b_r_consist = True
        if s_ctrl_lclip_clst != "-1:-1" and s_case_lclip_clst != "-1:-1":
            if abs(int(float(l_case_lclip[0]))-int(float(l_ctrl_lclip[1]))) < self.CLIP_CONSIST_DIST or \
                            abs(int(float(l_case_lclip[1]))-int(float(l_ctrl_lclip[0]))) < self.CLIP_CONSIST_DIST:
                b_l_consist = True
        return b_l_consist or b_r_consist

####
    def _is_disc_cluster_consist(self, s_case_ldisc_clst, s_case_rdisc_clst, s_ctrl_ldisc_clst, s_ctrl_rdisc_clst):
        l_ctrl_ldisc = s_ctrl_ldisc_clst.split(":")
        l_ctrl_rdisc = s_ctrl_rdisc_clst.split(":")
        l_case_ldisc = s_case_ldisc_clst.split(":")
        l_case_rdisc = s_case_rdisc_clst.split(":")

        b_l_consist = False
        b_r_consist = False

        if s_ctrl_rdisc_clst != "-1:-1" and s_case_rdisc_clst != "-1:-1":
            if abs(int(float(l_case_rdisc[0])) - int(float(l_ctrl_rdisc[0]))) < self.DISC_CONSIST_DIST or \
                            abs(int(float(l_case_rdisc[1])) - int(float(l_ctrl_rdisc[1]))) < self.DISC_CONSIST_DIST:
                b_r_consist = True
        if s_ctrl_ldisc_clst != "-1:-1" and s_case_ldisc_clst != "-1:-1":
            if abs(int(float(l_case_ldisc[0])) - int(float(l_ctrl_ldisc[0]))) < self.DISC_CONSIST_DIST or \
                            abs(int(float(l_case_ldisc[1])) - int(float(l_ctrl_ldisc[1]))) < self.DISC_CONSIST_DIST:
                b_l_consist = True
        ####
        if s_ctrl_rdisc_clst != "-1:-1" and s_case_rdisc_clst != "-1:-1":
            if abs(int(float(l_case_rdisc[0])) - int(float(l_ctrl_rdisc[1]))) < self.DISC_CONSIST_DIST or \
                            abs(int(float(l_case_rdisc[1])) - int(float(l_ctrl_rdisc[1]))) < self.DISC_CONSIST_DIST:
                b_r_consist = True
        if s_ctrl_ldisc_clst != "-1:-1" and s_case_ldisc_clst != "-1:-1":
            if abs(int(float(l_case_ldisc[1])) - int(float(l_ctrl_ldisc[0]))) < self.DISC_CONSIST_DIST or \
                            abs(int(float(l_case_ldisc[1])) - int(float(l_ctrl_ldisc[1]))) < self.DISC_CONSIST_DIST:
                b_l_consist = True
        return b_l_consist or b_r_consist

    def pass_gntp_features_chk(self, m_gntp_features, ins_chrm, ins_pos, ndisc_cutoff, nclip_cutoff, npolyA_cutoff):
        gntp_rcd = m_gntp_features[ins_chrm][ins_pos]
        n_af_clip = gntp_rcd[0]
        n_raw_clip = gntp_rcd[2] + gntp_rcd[3]
        n_disc = gntp_rcd[4]
        n_polyA = gntp_rcd[-2]
        n_disc_chrms = gntp_rcd[-1]

        ####potential issue is: if nearby there is another SV, may cause FN
        if n_disc > ndisc_cutoff and n_disc_chrms > 2:
            print("{0}:{1} is filtered out, as there are discordant reads in control".format(ins_chrm, ins_pos))
            return False
        if n_af_clip > nclip_cutoff and n_polyA > npolyA_cutoff:
            print("{0}:{1} is filtered out, as there are clipped reads (with polyA) in control".format(ins_chrm,
                                                                                                       ins_pos))
            return False
        return True

    def parse_high_confident_somatic(self, sf_hc_sites, sf_raw_somatic, sf_out):
        m_raw_somatic={}
        with open(sf_raw_somatic) as fin_somatic:
            for line in fin_somatic:
                fields=line.split()
                ins_chrm=fields[0]
                ins_pos=int(fields[1])
                if ins_chrm not in m_raw_somatic:
                    m_raw_somatic[ins_chrm]={}
                m_raw_somatic[ins_chrm][ins_pos]=1
        with open(sf_out, "w") as fout, open(sf_hc_sites) as fin_sites:
            for line in fin_sites:
                fields=line.split()
                ins_chrm = fields[0]
                ins_pos = int(fields[1])
                if (ins_chrm not in m_raw_somatic) or (ins_pos not in m_raw_somatic[ins_chrm]):
                    continue
                fout.write(line)
####
####
class CaseControlMode_old():
    def __init__(self, s_wfolder):
        self.s_wfolder=s_wfolder
        if os.path.exists(s_wfolder)==False:
            self.s_wfolder="./"
        elif s_wfolder[-1]!="/":
            s_wfolder+="/"

    ####load in the match between sample_id and the id parsed from bam
    def load_in_sample_id_vs_used_one(self, sf_id):
        m_indpdt_vs_bam_id={}
        m_bam_id_vs_indpdt={}
        with open(sf_id) as fin_id:
            for line in fin_id:
                fields=line.split()
                indpdt_id=fields[0]
                id_from_bam=fields[1]
                m_indpdt_vs_bam_id[indpdt_id]=id_from_bam
                m_bam_id_vs_indpdt[id_from_bam]=indpdt_id
        return m_indpdt_vs_bam_id, m_bam_id_vs_indpdt
####

    #for each line: "s_id sf_case sf_control"
    def load_in_samples(self, sf_idx):
        m_sf_case_control={}
        with open(sf_idx) as fin_idx:
            for line in fin_idx:
                fields=line.split()
                s_id=fields[0]
                sf_case=fields[1]
                sf_control=fields[2]
                m_sf_case_control[s_id]=(sf_case, sf_control)
        return m_sf_case_control

    # load the sites from file
    def load_sites(self, sf_ce):##
        m_MEI = {}
        with open(sf_ce) as fin_ce:
            for line in fin_ce:
                fields = line.split()
                chrm = fields[0]
                pos = int(fields[1])
                sinfo="\t".join(fields[2:])
                if chrm not in m_MEI:
                    m_MEI[chrm] = {}
                if pos not in m_MEI[chrm]:
                    m_MEI[chrm][pos] = sinfo
        return m_MEI
####

    # #filter out the germline events from 1000G released results
    def cmp_case_control(self, m_case, m_control, islack):
        m_candidates={}
        for chrm in m_case:#doesn't have this chrm
            if chrm not in m_control:
                if chrm not in m_candidates:
                    m_candidates[chrm]={}
                for pos in m_case[chrm]:
                    m_candidates[chrm][pos]=m_case[chrm][pos]
            else:###have this chrm
                for pos in m_case[chrm]:
                    b_exist = False
                    for i in range(-1 * islack, islack):
                        if (pos + i) in m_control[chrm]:
                            b_exist = True
                            break
                    if b_exist==False:
                        if chrm not in m_candidates:
                            m_candidates[chrm]={}
                        m_candidates[chrm][pos]=m_case[chrm][pos]
        return m_candidates

####
    def _load_in_rslt_list(self, sf_rslt_list, b_process):
        m_rslt_list={}
        with open(sf_rslt_list) as fin_rslt_list:
            for line in fin_rslt_list:
                fields=line.split()
                sid=fields[0]
                s_rslt=fields[1]
                if b_process==True:
                    sid_fields=sid.split("_")
                    sid="_".join(sid_fields[:-1])

                m_rslt_list[sid]=s_rslt
        return m_rslt_list

####
    def prepare_case_control_idx(self, sf_id_vs_id, slist_case_rslt, slist_control_rslt, sf_out_idx):
        m_indpdt_vs_bam_id, m_bam_id_vs_indpdt=self.load_in_sample_id_vs_used_one(sf_id_vs_id)
        #print m_bam_id_vs_indpdt
        m_case_list=self._load_in_rslt_list(slist_case_rslt, False)
        #print m_case_list
        m_control_list=self._load_in_rslt_list(slist_control_rslt, True)
        print(m_control_list)
        with open(sf_out_idx,"w") as fout_idx:
            for s_bam_id in m_bam_id_vs_indpdt:
                if s_bam_id not in m_case_list:
                    print(s_bam_id, "do not have a case result!!!")
                    continue
                sf_case=m_case_list[s_bam_id]

                s_sample_id=m_bam_id_vs_indpdt[s_bam_id]
                if s_sample_id not in m_control_list:
                    print("{0} do not have a control!!!".format(s_sample_id))
                    continue
                sf_control=m_control_list[s_sample_id]

                sinfo="{0}\t{1}\t{2}\n".format(s_bam_id, sf_case, sf_control)
                fout_idx.write(sinfo)

####
    def call_somatic_cases(self, sf_id_vs_id, slist_case_rslt, slist_control_rslt, islack):
        sf_idx=self.s_wfolder+"matched_case_control_rslt.list"
        self.prepare_case_control_idx(sf_id_vs_id, slist_case_rslt, slist_control_rslt, sf_idx)

        m_sf_case_control=self.load_in_samples(sf_idx)
        for s_id in m_sf_case_control:
            sf_case=m_sf_case_control[s_id][0]
            sf_control=m_sf_case_control[s_id][1]
            m_case=self.load_sites(sf_case)
            m_control=self.load_sites(sf_control)

            m_candidates=self.cmp_case_control(m_case, m_control, islack)
            sf_out=self.s_wfolder+s_id+".somatic"
####
            with open(sf_out, "w") as fout_rslt:
                for chrm in m_candidates:
                    for pos in m_candidates[chrm]:
                        sinfo="{0}\t{1}\t{2}\n".format(chrm, pos, m_candidates[chrm][pos])
                        fout_rslt.write(sinfo)
####

####
class SomaticMEICaller():#
    def __init__(self, sf_ref):
        self.reference=sf_ref

    def process_chrm_name(self, schrm):
        if len(schrm) > 3 and schrm[:3] == "chr":
            return schrm[3:]
        else:
            return schrm

    # load the sites from file
    def load_sites(self, sf_ce):
        m_MEI = {}
        with open(sf_ce) as fin_ce:
            for line in fin_ce:
                fields = line.split()
                chrm1 = fields[0]
                chrm=self.process_chrm_name(chrm1)
                pos = int(fields[1])
                if chrm not in m_MEI:
                    m_MEI[chrm] = {}
                if pos not in m_MEI[chrm]:
                    m_MEI[chrm][pos] = line
        return m_MEI

    # get the candidate sites happen in both lists
    def get_overlap(self, m1, m2, slack):
        m_shared = {}
        for chrm in m1:
            if chrm in m2:
                for pos in m1[chrm]:
                    for i in range(-1 * slack, slack):
                        if (pos + i) in m2[chrm]:
                            if chrm not in m_shared:
                                m_shared[chrm] = {}
                            m_shared[chrm][pos] = 1
                            break
        return m_shared

    # find out the mosaic events with case, control and germline datasets
    def call_mosaic_from_case_control(self, sf_case, sf_control, sf_1kg, islack, sf_out):
        m_all_case = self.load_sites(sf_case)
        m_somatic = self.filter_by_given_list(sf_1kg, m_all_case, islack)
        m_mosaic = self.filter_by_given_list(sf_control, m_somatic, islack)

        ####
        with open(sf_out, "w") as fout_rslt:
            for chrm in m_mosaic:
                for pos in m_mosaic[chrm]:
                    s_info = "{0}\t{1}\n".format(chrm, pos)
                    fout_rslt.write(s_info)

####
    ##filter out the germline events from germline database
    def filter_by_given_list(self, sf_db, m_MEIs, islack):
        m_candidates={}
        m_db=self.load_sites(sf_db)
        for chrm in m_MEIs:#doesn't have this chrm
            if chrm not in m_db:
                if chrm not in m_candidates:
                    m_candidates[chrm]={}
                for pos in m_MEIs[chrm]:
                    m_candidates[chrm][pos]=1
            else:###have this chrm
                for pos in m_MEIs[chrm]:
                    b_exist = False
                    for i in range(-1 * islack, islack):
                        if (pos + i) in m_db[chrm]:
                            b_exist = True
                            break
                    if b_exist==False:
                        if chrm not in m_candidates:
                            m_candidates[chrm]={}
                        m_candidates[chrm][pos]=m_MEIs[chrm][pos]
        return m_candidates

    #export the selected candidates to a file
    def export_slcted_candidates(self, m_MEIs, sf_out):
        with open(sf_out, "w") as fout_mei:
            for chrm in m_MEIs:
                for pos in m_MEIs[chrm]:
                    s_line=m_MEIs[chrm][pos]
                    fout_mei.write(s_line)

####
    # filter out FP by allele frequency
    def filter_by_AF(self, sf_bam_list, sf_candidate_list, extnd, clip_slack, s_working_folder, n_jobs, af_cutoff,
                     sf_output):
        xcd = XClipDisc(sf_bam_list, s_working_folder, n_jobs, self.reference)
        xcd.calc_AF_by_clip_reads_of_given_list(sf_bam_list, sf_candidate_list, extnd, clip_slack, af_cutoff, sf_output)

    # m_black_list in format: {chrm:[]}
    def is_within_blacklist_region(self, m_black_list, chrm, pos):
        if chrm not in m_black_list:
            return False
        lo, hi = 0, len(m_black_list[chrm]) - 1
        while lo <= hi:
            mid = (lo + hi) / 2
            mid_start_pos = m_black_list[chrm][mid][0]
            mid_end_pos = m_black_list[chrm][mid][1]
            if pos >= mid_start_pos and pos <= mid_end_pos:
                return True
            elif pos > mid_start_pos:
                lo = mid + 1
            else:
                hi = mid - 1
        return False

    # filter out the candidates by black list
    def filter_by_black_list(self, sf_candidate_list, sf_black_list, sf_out):
        m_black_list = {}
        with open(sf_black_list) as fin_black_list:
            for line in fin_black_list:
                fields = line.split()
                chrm_1 = fields[0]
                chrm = self.process_chrm_name(chrm_1)  # remove the "chr" is exists
                start = int(fields[1])
                end = int(fields[2])
                if chrm not in m_black_list:
                    m_black_list[chrm] = []
                m_black_list[chrm].append((start, end))  # assume the list has been sorted

        with open(sf_candidate_list) as fin_list, open(sf_out, "w") as fout_list:
            for line in fin_list:
                fields = line.split()
                chrm_1 = fields[0]
                ins_chrm = self.process_chrm_name(chrm_1)
                ins_pos = int(fields[1])
                # now check whether hit the black list region
                if self.is_within_blacklist_region(m_black_list, ins_chrm, ins_pos) == True:
                    continue
                fout_list.write(line)

    # filter out the germline events from 1000G released results
    def filter_by_germline_list(self, sf_1KG, sf_candidate, islack, sf_out):
        m_1kg = self.load_sites(sf_1KG)
        with open(sf_candidate) as fin_mei, open(sf_out, "w") as fout_rslts:
            for line in fin_mei:
                fields = line.split()
                chrm = fields[0]
                pos = int(fields[1])

                if chrm not in m_1kg:
                    fout_rslts.write(line)
                else:  ###have this chrm
                    b_exist = False
                    for i in range(-1 * islack, islack):
                        if (pos + i) in m_1kg[chrm]:
                            b_exist = True
                            break
                    if b_exist == False:
                        fout_rslts.write(line)

#awk -F "," '{cnt=$2+$3+$4+$5; if(cnt==1){print $0}}' intersect_picked_neuron.csv > intersect_picked_neuron_single.txt
##########################################################################
    #This version is to call
    def call_somatic_from_case_control(self, sf_case, sf_control, islack, sf_out):
        m_all_case = self.load_sites(sf_case)

#####
# def parse_option():
#     parser = OptionParser()
#     parser.add_option("-i", "--input", dest="input",
#                       help="input file ", metavar="FILE")
#     parser.add_option("--case", dest="case",
#                       help="case results list", metavar="FILE")
#     parser.add_option("--control", dest="control",
#                       help="control results list", metavar="FILE")
#     parser.add_option("-p", "--wfolder", dest="wfolder", type="string",
#                       help="Working folder")
#     parser.add_option("-e", "--slack", dest="slack", type="int",
#                       help="slack value for comparing two positions")
#     (options, args) = parser.parse_args()
#     return (options, args)
#
# ####
# ####
# if __name__ == '__main__':
#     (options, args) = parse_option()
#     sf_vs_ids=options.input
#     sf_case_list=options.case
#     sf_control_list=options.control
#     s_wfolder=options.wfolder
#     i_slack=options.slack
#
#     case_control_mode=CaseControlMode(s_wfolder)
#     case_control_mode.call_somatic_cases(sf_vs_ids, sf_case_list, sf_control_list, i_slack)
####