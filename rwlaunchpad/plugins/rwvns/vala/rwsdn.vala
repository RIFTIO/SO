namespace RwSdn {

  public interface Topology: GLib.Object {
    /*
     * Init routine
     */
    public abstract RwTypes.RwStatus init(RwLog.Ctx log_ctx);

    /*
     * Credential Validation related APIs
     */
    public abstract RwTypes.RwStatus validate_sdn_creds(
      Rwsdnal.SDNAccount account,
      out Rwsdnal.SdnConnectionStatus status);

    /*
     * Configuring  related APIs
     */
    /* TODO */

    /*
     * Network related APIs
     */
    public abstract RwTypes.RwStatus get_network_list(
      Rwsdnal.SDNAccount account,
      out RwTopology.YangData_IetfNetwork network_topology);
   
    /*
     * VNFFG Chain related APIs
     */
    public abstract RwTypes.RwStatus create_vnffg_chain(
      Rwsdnal.SDNAccount account,
      Rwsdnal.VNFFGChain vnffg_chain,
      out string vnffg_id);

    /*
     * VNFFG Chain Terminate related APIs
     */
    public abstract RwTypes.RwStatus terminate_vnffg_chain(
      Rwsdnal.SDNAccount account,
      string vnffg_id);


    /*
     * Network related APIs
     */
    public abstract RwTypes.RwStatus get_vnffg_rendered_paths(
      Rwsdnal.SDNAccount account,
      out Rwsdnal.VNFFGRenderedPaths rendered_paths);

    /*
     * Classifier related APIs
     */
    public abstract RwTypes.RwStatus create_vnffg_classifier(
      Rwsdnal.SDNAccount account,
      Rwsdnal.VNFFGClassifier vnffg_classifier, 
      [CCode (array_length = false, array_null_terminated = true)]
      out string [] vnffg_classifier_id);

    /*
     * Classifier related APIs
     */
    public abstract RwTypes.RwStatus terminate_vnffg_classifier(
      Rwsdnal.SDNAccount account,
      [CCode (array_length = false, array_null_terminated = true)]
      string [] vnffg_classifier_id);



    /*
     * Node Related APIs
     */
     /* TODO */

    /*
     * Termination-point Related APIs
     */
     /* TODO */

    /*
     * Link Related APIs
     */
     /* TODO */
    
  }
}


