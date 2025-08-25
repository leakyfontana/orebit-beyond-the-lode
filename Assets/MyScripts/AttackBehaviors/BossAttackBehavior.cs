using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class BossAttackBehavior : MonoBehaviour
{
	public int damage;
	
	void OnTriggerEnter2D(Collider2D col){
		if (col.gameObject.tag == "Player"){
			print("Entered attack");
			col.gameObject.GetComponent<PlayerMovement>().loseHP(damage);
		}
	}
}
