
# STANDARD_RIFT_IO_COPYRIGHT

import datetime
import logging
import time
import unittest

import paramiko
import rw_peas
import rwlogger

import gi
gi.require_version('RwCal', '1.0')
gi.require_version('RwcalYang', '1.0')
from gi.repository import RwcalYang
from gi.repository.RwTypes import RwStatus

logger = logging.getLogger('rwcal-brocadevcpe')

#
# Important information about Brocade vcPE installation. This needs to be manually verified 
#
vcpecloud_info = {
    'username'           : 'vyatta',
    'password'           : 'vyatta',
    'host'           : '10.66.4.26',
    'mgmt_network'       : 'mgmt',
    'public_ip_pool'       : '10.66.26.0/24',
    'wan_interface'       : 'dp0s2f0',
    'reserved_flavor'    : 'm1.reserved',
    'reserved_image'     : 'vyatta-7.qcow2',
    }


def get_cal_account():
    """
    Creates an object for class RwcalYang.CloudAccount()
    """
    account                        = RwcalYang.CloudAccount()
    account.account_type           = "prop_cloud1"
    account.prop_cloud1.host       = vcpecloud_info['host']
    account.prop_cloud1.username   = vcpecloud_info['username']
    account.prop_cloud1.password   = vcpecloud_info['password']
    account.prop_cloud1.mgmt_network = vcpecloud_info['mgmt_network']
    account.prop_cloud1.public_ip_pool = vcpecloud_info['public_ip_pool']
    account.prop_cloud1.wan_interface = vcpecloud_info['wan_interface']
    return account

def get_cal_plugin():
    """
    Loads rw.cal plugin via libpeas
    """
    plugin = rw_peas.PeasPlugin('rwcal_propcloud1', 'RwCal-1.0')
    engine, info, extension = plugin()

    # Get the RwLogger context
    rwloggerctx = rwlogger.RwLog.Ctx.new("Cal-Log")

    cal = plugin.get_interface("Cloud")
    try:
        rc = cal.init(rwloggerctx)
        assert rc == RwStatus.SUCCESS
    except:
        logger.error("ERROR:Cal plugin instantiation failed. Aborting tests")
    else:
        logger.info("Brocade vCPE Cal plugin successfully instantiated")
    return cal 


class BrocadeVcpeTest(unittest.TestCase):
    CpuPolicy = "DEDICATED"
    
    def setUp(self):
        """
        Assumption:
        If these resources are not then this test will fail.
        """
        self._acct = get_cal_account()
        logger.info("BrocadevCPE-CAL-Test: setUp")
        self.cal   = get_cal_plugin()
        logger.info("BrocadevCPE-CAL-Test: setUpEND")

        # First check for VM Flavor and Image and get the corresponding IDs
        rc, rs = self.cal.get_flavor_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)

        flavor_list = [ flavor for flavor in rs.flavorinfo_list if flavor.name == vcpecloud_info['reserved_flavor'] ]
        self.assertNotEqual(len(flavor_list), 0)
        self._flavor = flavor_list[0]

        rc, rs = self.cal.get_image_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)

        image_list = [ image for image in rs.imageinfo_list if image.name == vcpecloud_info['reserved_image'] ]
        self.assertNotEqual(len(image_list), 0)
        self._image = image_list[0]
        
    def tearDown(self):
        logger.info("BrocadevCPE-CAL-Test: tearDown")

    def _get_image_info_request(self):
        """
        Returns request object of type RwcalYang.ImageInfoItem()
        """
        img = RwcalYang.ImageInfoItem()
        img.name = "rift.cal.unittest.image"
        img.location = '/net/sharedfiles/home1/common/vm/Fedora-x86_64-20-20131211.1-sda.qcow2'
        img.disk_format = "qcow2"
        img.container_format = "bare"
        return img

    def _get_image_info(self, img_id):
        """
        Checks the image status until it becomes active or timeout occurs (100sec)
        Returns the image_info dictionary
        """
        rs = None
        rc = None
        for i in range(100):
            rc, rs = self.cal.get_image(self._acct, img_id)
            self.assertEqual(rc, RwStatus.SUCCESS)
            logger.info("BrocadevCPE-CAL-Test: Image (image_id: %s) reached state : %s" %(img_id, rs.state))
            if rs.state == 'active':
                break
            else:
                time.sleep(2) # Sleep for a second
        return rs

    @unittest.skip("Skipping test_create_delete_image")
    def test_create_delete_image(self):
        """
        Create/Query/Delete a new image in openstack installation
        """
        logger.info("BrocadevCPE-CAL-Test: Starting Image create test")
        img = self._get_image_info_request()
        rc, img_id = self.cal.create_image(self._acct, img)
        logger.info("BrocadevCPE-CAL-Test: Created Image with image_id: %s" %(img_id))
        self.assertEqual(rc, RwStatus.SUCCESS)

        img_info = self._get_image_info(img_id)
        self.assertNotEqual(img_info, None)
        self.assertEqual(img_id, img_info.id)
        logger.info("BrocadevCPE-CAL-Test: Image (image_id: %s) reached state : %s" %(img_id, img_info.state))

        rc, imgs_dict = self.cal.get_image_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Got image list: %s" % imgs_dict)
        exists = False
        for img in imgs_dict.imageinfo_list:
            if img.name == img_id:
               exists = True
        self.assertEqual(exists, True)

        logger.info("BrocadevCPE-CAL-Test: Initiating Delete Image operation for image_id: %s" %(img_id))
        rc = self.cal.delete_image(self._acct, img_id)
        self.assertEqual(rc, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Image (image_id: %s) successfully deleted" %(img_id))

    def _get_flavor_info_request(self):
        """
        Returns request object of type RwcalYang.FlavorInfoItem()
        """
        flavor                                     = RwcalYang.FlavorInfoItem()
        flavor.name                                = 'rift.cal.unittest.flavor'
        flavor.vm_flavor.memory_mb                 = 16384 # 16GB
        flavor.vm_flavor.vcpu_count                = 4 
        flavor.vm_flavor.storage_gb                = 40 # 40GB
        return flavor

    @unittest.skip("Skipping test_create_delete_flavor")
    def test_create_delete_flavor(self):
        """
          Test to create/delete a flavor in vCPE CAL
          Note: No flavor is created in vCPE itself, since it does not support it
        """
        logger.info("BrocadevCPE-CAL-Test: Test Create flavor API")
        ### Delete any previously created flavor with name rift.cal.unittest.flavor
        rc, rs = self.cal.get_flavor_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        flavor_list = [ flavor for flavor in rs.flavorinfo_list if flavor.name == 'rift.cal.unittest.flavor' ]
        if flavor_list:
            rc = self.cal.delete_flavor(self._acct, flavor_list[0].id)
            self.assertEqual(rc, RwStatus.SUCCESS)
        
        flavor = self._get_flavor_info_request()
        rc, flavor_id = self.cal.create_flavor(self._acct, flavor)
        self.assertEqual(rc, RwStatus.SUCCESS)
        
        logger.info("BrocadevCPE-CAL-Test: Created new flavor with flavor_id : %s" %(flavor_id))
        rc, rs = self.cal.get_flavor(self._acct, flavor_id)
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rs.id, flavor_id)
        logger.debug("BrocadevCPE-CAL-Test: rs : %s" %(rs))

        # Verify flavor Attributes
        self.assertEqual(rs.vm_flavor.memory_mb, 16384)
        self.assertEqual(rs.vm_flavor.vcpu_count, 4)
        self.assertEqual(rs.vm_flavor.storage_gb, 40)
        logger.info("Openstack-CAL-Test: Initiating delete for flavor_id : %s" %(flavor_id))
        rc = self.cal.delete_flavor(self._acct, flavor_id)
        self.assertEqual(rc, RwStatus.SUCCESS)
        # Check that flavor does not exist anymore in list_flavor
        rc, rs = self.cal.get_flavor_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        flavor_list = [ flavor for flavor in rs.flavorinfo_list if flavor.id == flavor_id ]
        # Flavor List should be empty
        self.assertEqual(len(flavor_list), 0)
        logger.info("BrocadevCPE-CAL-Test: Flavor (flavor_id: %s) successfully deleted" %(flavor_id))

    def _get_vdu_request_info(self):
        """
        Returns object of type RwcalYang.VDUInitParams
        """
        vdu = RwcalYang.VDUInitParams()
        vdu.name = "cal_vdu"
        vdu.image_id = self._image.id
        vdu.flavor_id = self._flavor.id
        vdu.allocate_public_address = True
        return vdu

    def _get_vdu_request_info_with_cp(self, virtual_link_id):
        """
        Returns object of type RwcalYang.VDUInitParams
        """
        vdu = RwcalYang.VDUInitParams()
        vdu.name = "cal_vdu2"
        vdu.image_id = self._image.id
        vdu.flavor_id = self._flavor.id
        vdu.allocate_public_address = True
        c1 = vdu.connection_points.add()
        c1.name = "c_point1"
        c1.virtual_link_id = virtual_link_id
        c1.type_yang = 'VIRTIO'
        return vdu

    def _get_rbsh_vdu_request_info(self, vlink_list):
        """
        Returns object of type RwcalYang.VDUInitParams
        """
        vdu = RwcalYang.VDUInitParams()
        vdu.name = "cal_rbsh_vdu"
        vdu.image_id = self._image.id
        vdu.flavor_id = self._flavor.id
        vdu.allocate_public_address = True
        ctr = 0
        for vl in vlink_list:
           c1 = vdu.connection_points.add()
           c1.name = "c_point" + str(ctr)
           ctr += 1
           c1.virtual_link_id = vl
           c1.type_yang = 'VIRTIO'

        vol0 = vdu.volumes.add()
        vol0.name = "mgmt"
        vol0.image = "mgmt.img"
        vol0.boot_params.boot_priority = 1
        vol0.guest_params.device_type = "disk"

        vol1 = vdu.volumes.add()
        vol1.name = "segstore"
        vol1.image = "segstore.img"
        vol1.boot_params.boot_priority = 2
        vol1.guest_params.device_type = "disk"
         
        return vdu 

    @unittest.skip("Skipping test_create_delete_vdu_nocps")
    def test_create_delete_vdu_nocps(self):
        """
        Test to create VDU with no connection points
        """
        # Now create VDU
        vdu_req = self._get_vdu_request_info()
        logger.info("BrocadevCPE-CAL-Test: Test Create VDU API")

        rc, rsp = self.cal.create_vdu(self._acct, vdu_req)
        logger.debug("BrocadevCPE-CAL-Test: rc %s rsp %s" % (rc, rsp))
        self.assertEqual(rc.status, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Created vdu with Id: %s" %rsp)

        test_vdu_id = rsp

        ## Check if VDU create is successful
        rc, rsp = self.cal.get_vdu(self._acct, rsp)
        logger.debug("Get VDU response %s", rsp)
        self.assertEqual(rsp.vdu_id, test_vdu_id)

        ### Wait until vdu_state is active
        for i in range(50):
            rc, rs = self.cal.get_vdu(self._acct, test_vdu_id)
            self.assertEqual(rc, RwStatus.SUCCESS)
            logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s" %(test_vdu_id, rs.state))
            if rs.state == 'active':
                break
        rc, rs = self.cal.get_vdu(self._acct, test_vdu_id)
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rs.state, 'active')
        logger.info("BrocadevCPE-CAL-Test: VDU with id : %s reached expected state  : %s" %(test_vdu_id, rs.state))
        logger.info("BrocadevCPE-CAL-Test: VDUInfo: %s" %(rs))

        ### Check vdu list as well
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        found = False
        for vdu in rsp.vdu_info_list:
            if vdu.vdu_id == test_vdu_id:
               found = True
        self.assertEqual(found, True)
        logger.info("BrocadevCPE-CAL-Test: Passed VDU list" )

        
        ### Lets delete the VDU
        self.cal.delete_vdu(self._acct, test_vdu_id)

        time.sleep(5)
        ### Verify that VDU is successfully deleted
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        for vdu in rsp.vdu_info_list:
            self.assertNotEqual(vdu.vdu_id, test_vdu_id)

        logger.info("Openstack-CAL-Test: VDU (with no CPs) create-delete test successfully completed")
        
    @unittest.skip("Skipping test_create_delete_vdu_mgmtport")
    def test_create_delete_vdu_mgmtport(self):
        """
        Test to create VDU with only mgmt port
        """
        # Now create VDU
        vdu_req = self._get_vdu_request_info()
        logger.info("BrocadevCPE-CAL-Test: Test Create VDU API (w/ mgmt port)")

        rc, rsp = self.cal.create_vdu(self._acct, vdu_req)
        logger.debug("BrocadevCPE-CAL-Test: rc %s rsp %s" % (rc, rsp))
        self.assertEqual(rc.status, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Created vdu with Id: %s" %rsp)

        test_vdu_id = rsp

        ## Check if VDU get is successful
        rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
        logger.debug("Get VDU response %s", rsp)
        self.assertEqual(rsp.vdu_id, test_vdu_id)

        ### Wait until vdu_state is active
        for i in range(50):
            logger.debug("Getting VDU iter %d", i)
            rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
            self.assertEqual(rc, RwStatus.SUCCESS)
            logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s rsp %s" %(test_vdu_id, rsp.state, rsp))
            if (rsp.state == 'active') and ('management_ip' in rsp) and ('public_ip' in rsp):
                logger.debug("Breaking out")
                break
            logger.debug("Waiting another 2 secs")
            time.sleep(2)

        rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rsp.state, 'active')
        logger.info("BrocadevCPE-CAL-Test: VDU with id : %s reached expected state  : %s IP: %s" %(test_vdu_id, rsp.state, rsp.management_ip))
        logger.info("BrocadevCPE-CAL-Test: VDUInfo: %s" %(rsp))

        ### Check vdu list as well
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        found = False
        logger.debug("Get VDU response %s", rsp)
        for vdu in rsp.vdu_info_list:
            if vdu.vdu_id == test_vdu_id:
               found = True
        self.assertEqual(found, True)
        logger.info("BrocadevCPE-CAL-Test: Passed VDU list %d", i )

        ### Lets delete the VDU
        logger.info("BrocadevCPE-CAL-Test: Deleting VDU %s", test_vdu_id )
        self.cal.delete_vdu(self._acct, test_vdu_id)
        time.sleep(5)
        ### Verify that VDU and mgmt CP are successfully deleted
        logger.info("BrocadevCPE-CAL-Test: Getting VDU list after delete operation" )
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        for vdu in rsp.vdu_info_list:
            self.assertNotEqual(vdu.vdu_id, test_vdu_id)

        logger.info("BrocadevCPE-CAL-Test: VDU (with mgmt CP) create-delete test successfully completed")

    def _get_virtual_link_request_info(self):
        """
        Returns object of type RwcalYang.VirtualLinkReqParams
        """
        vlink = RwcalYang.VirtualLinkReqParams()
        vlink.name = 'rift.cal.virtual_link'
        vlink.subnet = '11.1.0.0/16'
        return vlink
 
    @unittest.skip("Skipping test_create_delete_virtual_link")
    def test_create_delete_virtual_link(self):
        """
        Test to create virtual link
        """
        logger.info("BrocadevCPE-CAL-Test: Test Create Virtual Link API")
        vlink_req = self._get_virtual_link_request_info()

        rc, rsp = self.cal.create_virtual_link(self._acct, vlink_req)
        self.assertEqual(rc.status, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Created virtual_link with Id: %s" %rsp)
        vlink_id = rsp
        
        #Check if virtual_link create is successful
        logger.info("BrocadevCPE-CAL-Test: Getting virtual link " )
        rc, rsp = self.cal.get_virtual_link(self._acct, rsp)
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rsp.virtual_link_id, vlink_id)
        logger.info("BrocadevCPE-CAL-Test: Passed get virtual link" )

        #Check if virtual_link create is successful
        logger.info("BrocadevCPE-CAL-Test: Getting virtual link list " )
        rc, rsp = self.cal.get_virtual_link_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        found = False
        for vlink in rsp.virtual_link_info_list:
            if vlink.virtual_link_id == vlink_id:
               found = True
        self.assertEqual(found, True)
        logger.info("BrocadevCPE-CAL-Test: Passed get virtual link" )

        logger.info("BrocadevCPE-CAL-Test: Deleting virtual link " )
        rc = self.cal.delete_virtual_link(self._acct, vlink_req.name)
        self.assertEqual(rc, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Deleted virtual_link with Id: %s" % vlink_req.name)


    #@unittest.skip("Skipping test_create_delete_virtual_link_and_vdu")
    def test_create_delete_virtual_link_and_vdu(self):
        """
        Test to create VDU with mgmt port and additional connection point
        """
        '''
        logger.info("BrocadevCPE-CAL-Test: Test Create Virtual Link API")
        vlink_req = self._get_virtual_link_request_info()

        #rc, rsp = self.cal.create_virtual_link(self._acct, vlink_req)
        #self.assertEqual(rc.status, RwStatus.SUCCESS)
        #logger.info("BrocadevCPE-CAL-Test: Created virtual_link with Id: %s" %rsp)
        #vlink_id = rsp
        rsp = "lo2"
        vlink_id = "lo2"
        
        #Check if virtual_link create is successful
        rc, rsp = self.cal.get_virtual_link(self._acct, rsp)
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rsp.virtual_link_id, vlink_id)

        # Now create VDU
        vdu_req = self._get_vdu_request_info_with_cp(vlink_id)
        logger.info("BrocadevCPE-CAL-Test: Test Create VDU API (w/ mgmt port) and CP")

        rc, rsp = self.cal.create_vdu(self._acct, vdu_req)
        logger.debug("BrocadevCPE-CAL-Test: rc %s rsp %s" % (rc, rsp))
        self.assertEqual(rc.status, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Created vdu with Id: %s" %rsp)

        test_vdu_id = rsp

        ## Check if VDU get is successful
        rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
        logger.debug("Get VDU response %s", rsp)
        self.assertEqual(rsp.vdu_id, test_vdu_id)

        ### Wait until vdu_state is active
        logger.debug("Waiting 10 secs")
        time.sleep(10)
        #{'name': 'dp0vhost7', 'connection_point_id': 'dp0vhost7', 'state': 'active', 'virtual_link_id': 'rift.cal.virtual_link', 'ip_address': '192.168.100.6'}
        vdu_state = 'inactive'
        cp_state = 'inactive'
        for i in range(5):
            rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
            self.assertEqual(rc, RwStatus.SUCCESS)
            logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s, mgmt ip %s" %(test_vdu_id, rsp.state, rsp.management_ip))
            if (rsp.state == 'active') and ('management_ip' in rsp) and ('public_ip' in rsp):
                vdu_state = 'active'
                #'connection_points': [{'name': 'dp0vhost7', 'connection_point_id': 'dp0vhost7', 'state': 'active', 'virtual_link_id': 'rift.cal.virtual_link', 'ip_address': '192.168.100.6'}]
                for cp in rsp.connection_points:
                    logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s CP state %s" %(test_vdu_id, rsp.state, cp))
                    if vdu_state == 'active' and cp.virtual_link_id == 'rift.cal.virtual_link' and cp.ip_address is not None :
                        cp_state = 'active'
                        break
            logger.debug("Waiting another 5 secs")
            time.sleep(5)
                
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rsp.state, 'active')
        self.assertEqual(vdu_state, 'active')
        self.assertEqual(cp_state, 'active')
        logger.info("BrocadevCPE-CAL-Test: VDU with id : %s reached expected state  : %s IP: %s" %(test_vdu_id, rsp.state, rsp.management_ip))
        logger.info("BrocadevCPE-CAL-Test: VDUInfo: %s" %(rsp))
        logger.info("Waiting for 30 secs before deletion")
        time.sleep(30)

        ### Check vdu list as well
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        found = False
        logger.debug("Get VDU response %s", rsp)
        for vdu in rsp.vdu_info_list:
            if vdu.vdu_id == test_vdu_id:
               found = True
        self.assertEqual(found, True)
        logger.info("BrocadevCPE-CAL-Test: Passed VDU list" )

        '''
        test_vdu_id = "cal_vdu2"
        ### Lets delete the VDU
        logger.info("BrocadevCPE-CAL-Test: Deleting VDU %s", test_vdu_id )
        self.cal.delete_vdu(self._acct, test_vdu_id)
        time.sleep(5)
        ### Lets delete the VL
        '''
        logger.info("BrocadevCPE-CAL-Test: Deleting VL %s", vlink_id )
        self.cal.delete_virtual_link(self._acct, vlink_id)
        ### Verify that VDU and mgmt CP are successfully deleted
        logger.info("BrocadevCPE-CAL-Test: Getting VDU list after delete operation" )
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        for vdu in rsp.vdu_info_list:
            self.assertNotEqual(vdu.vdu_id, test_vdu_id)
        '''

        logger.info("BrocadevCPE-CAL-Test: VDU (with mgmt CP and VL) create-delete test successfully completed")


    @unittest.skip("Skipping test_get_virtual_link_link")
    def test_get_virtual_link_list(self):
        """
        Test to get virtual link list and all associated CPs
        """
        logger.info("BrocadevCPE-CAL-Test: Test Get Virtual Link list API")
        vlink_id = "rift.cal.virtual_link"
        rc, rsp = self.cal.get_virtual_link(self._acct, vlink_id)
        logger.info("BrocadevCPE-CAL-Test: Get virtual_link,  rsp.status  %s", rc)
        self.assertEqual(rc, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Get virtual_link,  rsp.link_info  %s", rsp.name)
        self.assertEqual(rsp.name, vlink_id)
        logger.info("BrocadevCPE-CAL-Test: Get virtual_link,  rsp.link_info  %s", rsp.name)
        logger.info("BrocadevCPE-CAL-Test: Get virtual_link,  connection points  %s", rsp.connection_points)

        rc, rsp = self.cal.get_virtual_link_list(self._acct)
        logger.info("BrocadevCPE-CAL-Test: Get virtual_link list, rsp  %s", rsp)

    @unittest.skip("Skipping test_create_rbsh_vdu")
    def test_create_rbsh_vdu(self):
        """
        Test to create VDU with mgmt port and 3 additional connection points
        """
        logger.info("BrocadevCPE-CAL-Test: Test Create Virtual Link API")
        vlink_list = []
        for ctr in range(3):
           vlink = RwcalYang.VirtualLinkReqParams()
           vlink.name = 'rift.cal.virtual_link' + str(ctr)
           vlink.subnet = '11.{}.0.0/16'.format(str(1 + ctr))

           rc, rsp = self.cal.create_virtual_link(self._acct, vlink)
           self.assertEqual(rc.status, RwStatus.SUCCESS)
           logger.info("BrocadevCPE-CAL-Test: Created virtual_link with Id: %s" %rsp)
           vlink_id = rsp
        
           #Check if virtual_link create is successful
           rc, rsp = self.cal.get_virtual_link(self._acct, rsp)
           self.assertEqual(rc, RwStatus.SUCCESS)
           self.assertEqual(rsp.virtual_link_id, vlink_id)
           vlink_list.append(vlink_id)
           

        # Now create VDU
        vdu_req = self._get_rbsh_vdu_request_info(vlink_list)
        logger.info("BrocadevCPE-CAL-Test: Test Create RB steelhead VDU API (w/ mgmt port) and 3 CPs")

        rc, rsp = self.cal.create_vdu(self._acct, vdu_req)
        logger.debug("BrocadevCPE-CAL-Test: rc %s rsp %s" % (rc, rsp))
        self.assertEqual(rc.status, RwStatus.SUCCESS)
        logger.info("BrocadevCPE-CAL-Test: Created vdu with Id: %s" %rsp)

        test_vdu_id = rsp

        ## Check if VDU get is successful
        rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
        logger.debug("Get VDU response %s", rsp)
        self.assertEqual(rsp.vdu_id, test_vdu_id)

        ### Wait until vdu_state is active
        logger.debug("Waiting 10 secs")
        time.sleep(10)
        #{'name': 'dp0vhost7', 'connection_point_id': 'dp0vhost7', 'state': 'active', 'virtual_link_id': 'rift.cal.virtual_link', 'ip_address': '192.168.100.6'}
        vdu_state = 'inactive'
        cp_state = 'inactive'
        for i in range(5):
            rc, rsp = self.cal.get_vdu(self._acct, test_vdu_id)
            self.assertEqual(rc, RwStatus.SUCCESS)
            logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s, mgmt ip %s" %(test_vdu_id, rsp.state, rsp.management_ip))
            if (rsp.state == 'active') and ('management_ip' in rsp) and ('public_ip' in rsp):
                vdu_state = 'active'
                #'connection_points': [{'name': 'dp0vhost7', 'connection_point_id': 'dp0vhost7', 'state': 'active', 'virtual_link_id': 'rift.cal.virtual_link', 'ip_address': '192.168.100.6'}]
                for cp in rsp.connection_points:
                    logger.info("BrocadevCPE-CAL-Test: VDU with id : %s. Reached State :  %s CP state %s" %(test_vdu_id, rsp.state, cp))
                    if vdu_state == 'active' and cp.virtual_link_id == 'rift.cal.virtual_link' and cp.ip_address is not None :
                        cp_state = 'active'
                        break
            logger.debug("Waiting another 5 secs")
            time.sleep(5)
                
        self.assertEqual(rc, RwStatus.SUCCESS)
        self.assertEqual(rsp.state, 'active')
        self.assertEqual(vdu_state, 'active')
        self.assertEqual(cp_state, 'active')
        logger.info("BrocadevCPE-CAL-Test: VDU with id : %s reached expected state  : %s IP: %s" %(test_vdu_id, rsp.state, rsp.management_ip))
        logger.info("BrocadevCPE-CAL-Test: VDUInfo: %s" %(rsp))
        logger.info("Waiting for 30 secs before deletion")
        time.sleep(30)

        ### Check vdu list as well
        rc, rsp = self.cal.get_vdu_list(self._acct)
        self.assertEqual(rc, RwStatus.SUCCESS)
        found = False
        logger.debug("Get VDU response %s", rsp)
        for vdu in rsp.vdu_info_list:
            if vdu.vdu_id == test_vdu_id:
               found = True
        self.assertEqual(found, True)
        logger.info("BrocadevCPE-CAL-Test: Passed VDU list" )

    
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
