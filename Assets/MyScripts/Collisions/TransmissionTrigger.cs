using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class TransmissionTrigger : MonoBehaviour
{
	public GameObject transmission_manager;
	public int transmission_index;

	void OnTriggerEnter2D(Collider2D col){
		if (col.gameObject.tag == "PlayerTrigger"){
			transmission_manager.GetComponent<TransmissionManager>().displayTransmission(transmission_index);
		}
	}
	
}
