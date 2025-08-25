using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class BackgroundChangeColorTrigger : MonoBehaviour
{
	public GameObject background_object;
	public Color color_goal;
	
	void OnTriggerEnter2D(Collider2D col){
		if (col.gameObject.tag == "PlayerTrigger"){
			background_object.GetComponent<BackgroundScript>().setNewGoal(color_goal);
		}
	}
}
