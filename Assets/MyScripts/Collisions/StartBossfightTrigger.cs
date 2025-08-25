using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class StartBossfightTrigger : MonoBehaviour
{
	public GameObject p1_boss;
	public GameObject player;
	public GameObject ceiling_collider;
	
	void OnTriggerEnter2D(Collider2D col){
		if (col.gameObject.tag == "PlayerTrigger"){
			player.GetComponent<PlayerMovement>().has_bossfight_started = true;
			FindObjectOfType<AudioManager>().PlayMusic("BossMusic");
			ceiling_collider.SetActive(true);
			p1_boss.SetActive(true);
			Destroy(gameObject);
		}
	}
}
