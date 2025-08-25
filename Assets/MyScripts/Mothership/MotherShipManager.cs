using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class MotherShipManager : MonoBehaviour
{
	public GameObject player;
	public GameObject transmission_manager;

	
	public void arrivalSound(){
		FindObjectOfType<AudioManager>().PlaySoundOneShot("MothershipArrive");
	}

	public void dropPlayer(){
		player.SetActive(true);
	}
	
	public void departSound(){
		FindObjectOfType<AudioManager>().PlaySoundOneShot("MothershipLeave");	
	}

	public void finishAnimation(){
		Destroy(gameObject);
		transmission_manager.GetComponent<TransmissionManager>().displayTransmission(0);
	}
}
